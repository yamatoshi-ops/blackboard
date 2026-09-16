"""Minimal forward/inverse flux-map interpolation used by fit and QA."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
from scipy.spatial import Delaunay, QhullError


TRIANGULATION_SOURCE_UNSPECIFIED = "UNSPECIFIED"
TRIANGULATION_SOURCE_DIRECT_FORWARD_MAP = "DIRECT_FORWARD_MAP"
TRIANGULATION_SOURCE_INVERSE_DERIVED_FROM_FORWARD_MAP = (
    "INVERSE_DERIVED_FROM_FORWARD_MAP"
)
TRIANGULATION_SOURCE_DIRECT_INVERSE_MAP = "DIRECT_INVERSE_MAP"
TRIANGULATION_SOURCE_FORWARD_DERIVED_FROM_INVERSE_MAP = (
    "FORWARD_DERIVED_FROM_INVERSE_MAP"
)


@dataclass(frozen=True)
class DQValue:
    d: Any
    q: Any


@dataclass(frozen=True)
class MapEvaluation:
    d: Any
    q: Any
    supported: Any
    nearest_fallback_used: Any


@dataclass(frozen=True)
class LinearTriangulation:
    points: np.ndarray
    simplices: np.ndarray
    output_d: np.ndarray
    output_q: np.ndarray
    source_kind: str = TRIANGULATION_SOURCE_UNSPECIFIED


def _broadcast(*values: object) -> tuple[list[np.ndarray], tuple[int, ...]]:
    try:
        arrays = [
            np.asarray(value, dtype=float)
            for value in values
        ]
        arrays = list(np.broadcast_arrays(*arrays))
    except (TypeError, ValueError) as error:
        raise ValueError("map query values must be numeric and broadcastable") from error
    if not all(np.isfinite(array).all() for array in arrays):
        raise ValueError("map query values must be finite")
    return arrays, arrays[0].shape


def _restore(values: object, shape: tuple[int, ...]) -> Any:
    array = np.asarray(values, dtype=float).reshape(shape)
    return float(array) if shape == () else array


def _restore_bool(values: object, shape: tuple[int, ...]) -> Any:
    array = np.asarray(values, dtype=bool).reshape(shape)
    return bool(array) if shape == () else array


def _axis(values: object, name: str) -> np.ndarray:
    try:
        axis = np.asarray(values, dtype=float).reshape(-1)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if len(axis) < 2 or not np.isfinite(axis).all():
        raise ValueError(f"{name} must contain at least two finite values")
    if not np.all(np.diff(axis) > 0.0):
        raise ValueError(f"{name} must be strictly increasing")
    return axis


class _ScatteredPairInterpolator:
    def __init__(
        self,
        x: object,
        y: object,
        output_d: object,
        output_q: object,
        *,
        name: str,
        source_kind: str,
    ):
        values = np.column_stack(
            [
                np.asarray(x, dtype=float).ravel(),
                np.asarray(y, dtype=float).ravel(),
                np.asarray(output_d, dtype=float).ravel(),
                np.asarray(output_q, dtype=float).ravel(),
            ]
        )
        if values.shape[0] < 3 or not np.isfinite(values).all():
            raise ValueError(
                f"{name} interpolation requires at least three finite source points"
            )

        coordinates = values[:, :2]
        unique_coordinates, first, inverse = np.unique(
            coordinates,
            axis=0,
            return_index=True,
            return_inverse=True,
        )
        if len(unique_coordinates) < 3:
            raise ValueError(
                f"{name} interpolation requires at least three unique coordinates"
            )
        source_order = np.argsort(first)
        remap = np.empty(len(source_order), dtype=int)
        remap[source_order] = np.arange(len(source_order))
        inverse = remap[inverse]
        unique_coordinates = unique_coordinates[source_order]
        reduced = np.empty((len(unique_coordinates), 2), dtype=float)
        for index in range(len(unique_coordinates)):
            reduced[index] = values[inverse == index, 2:].mean(axis=0)

        try:
            triangulation = Delaunay(unique_coordinates)
            linear_d = LinearNDInterpolator(
                triangulation,
                reduced[:, 0],
                fill_value=np.nan,
            )
            linear_q = LinearNDInterpolator(
                triangulation,
                reduced[:, 1],
                fill_value=np.nan,
            )
            nearest_d = NearestNDInterpolator(
                unique_coordinates,
                reduced[:, 0],
            )
            nearest_q = NearestNDInterpolator(
                unique_coordinates,
                reduced[:, 1],
            )
        except (QhullError, ValueError) as error:
            raise ValueError(f"{name} interpolation could not be constructed") from error

        self._points = unique_coordinates
        self._output_d = reduced[:, 0]
        self._output_q = reduced[:, 1]
        self._triangulation = triangulation
        self._linear_d = linear_d
        self._linear_q = linear_q
        self._nearest_d = nearest_d
        self._nearest_q = nearest_q
        self._source_kind = str(source_kind)

    def evaluate(
        self,
        x: object,
        y: object,
    ) -> tuple[Any, Any, Any, Any]:
        (x_array, y_array), shape = _broadcast(x, y)
        points = np.column_stack([x_array.ravel(), y_array.ravel()])
        supported = self._triangulation.find_simplex(points) >= 0
        output_d = np.asarray(self._linear_d(points), dtype=float).reshape(-1)
        output_q = np.asarray(self._linear_q(points), dtype=float).reshape(-1)
        fallback = (
            ~supported
            | ~np.isfinite(output_d)
            | ~np.isfinite(output_q)
        )
        if fallback.any():
            output_d[fallback] = np.asarray(
                self._nearest_d(points[fallback]),
                dtype=float,
            ).reshape(-1)
            output_q[fallback] = np.asarray(
                self._nearest_q(points[fallback]),
                dtype=float,
            ).reshape(-1)
        if not np.isfinite(output_d).all() or not np.isfinite(output_q).all():
            raise ValueError("map interpolation produced nonfinite values")
        return (
            _restore(output_d, shape),
            _restore(output_q, shape),
            _restore_bool(supported, shape),
            _restore_bool(fallback, shape),
        )

    def triangulation(self) -> LinearTriangulation:
        arrays = (
            np.array(self._points, copy=True),
            np.array(self._triangulation.simplices, copy=True),
            np.array(self._output_d, copy=True),
            np.array(self._output_q, copy=True),
        )
        for array in arrays:
            array.flags.writeable = False
        return LinearTriangulation(*arrays, source_kind=self._source_kind)
