# 工程①・②の進捗確認と工程③の実装結果

2026-09-17。既存の実装工程表に基づくソフトウェア実装の結果を記録する。
工程①〜③の独立実行経路を完成し、合成2モータで確認した。実データ精度・実機採用の判断は含めない。

## 工程①・②の確認

着手時はbranch `codex/coenergy-maps-extraction-plan`、HEAD `56a6615`、worktreeは変更なし。
工程①のJMAG VI→点磁束→保存Co-energy面と、工程②の共通同定CLIが実装済みだった。
前回の実装結果とコードを照合し、変更前の既存30 testsを再実行して全件成功した。

| 工程 | 確認した到達点 | 未確認事項 |
|---|---|---|
| ① | 合成2モータ各221行→117観測、保存prior、点別残差、モデル再評価 | 実JMAG full dataでの適合・精度 |
| ② | 共通mirror pair／Iq=0同定、任意列対応、元行・成分mask・計算不能理由の保存 | 実測取得条件への接続・精度 |

工程②の実装が未完了だったわけではなく、対象の実測データを接続する作業が残っていた。
今回も実データ一式の指定はなく、非ゼロの既知差分を持つ合成VIを追加して工程③を検証した。

## 工程③の実装

`run_build_maps.py --config <TOML>`を追加し、次をファイル経由で接続した。

1. 保存priorと工程②の点磁束を読み、成分mask・weightを引き継ぐ。計算不能行、非有限成分、core外を理由付きで保持する。
2. 固定priorと観測との差分だけをCo-energy面へFitする。C2 taperをCo-energyに掛け、積の解析微分から磁束・Hessianを得る。
3. prior・差分・supportを同梱した`final_model.npz`と残差を保存する。prior単独のNPZと設定・観測も出力先へ保持する。
4. 最終面を指定電流軸で評価し、小数8桁の公開順LUTを保存する。
5. 公開順LUTの425節点から、正規化したthin-plate-spline RBFで逆Fitし、小数6桁の逆LUTを保存する。
6. 凸包・格子・復元電流の範囲、Hessianと順LUT Jacobian、面／LUT差と往復誤差を保存する。

工程③の補正設定・順逆軸・精度・補間契約は実装前に[入力契約](input_output_contract.md)へ追加した。
既存の補正コアから適応選点を除き、逆Fitから必要な正規化・RBF・成分評価、map評価から必要な補間器を抽出した。
DEN固有の格子・CV・近接点merge・レポート用pipelineは持ち込んでいない。
設定例の補正Fitは19自由度、88観測・165有効成分、正則化0。実データ向けの推奨設定ではない。

逆軸の丸め重複、同一公開磁束に異なる電流が対応する衝突、逆Fit条件不成立を理由付きで保存する。
逆工程が失敗しても保存済み最終面・順LUT・補正残差を残す。非空出力先は上書きしない。

## 検証結果

macOS arm64、Python 3.13.7、NumPy 2.5.3、SciPy 1.18.1、pandas 2.3.3。
`pip check`は依存不整合なし。対象フォルダの`unittest`全49件が成功（skipなし）。
元repositoryを含まない空白付きの別フォルダへコピーし、新規venvへ依存を導入した場合も49件成功、
2モータの①〜③がすべて終了コード0だった。`PYTHONPATH`を外し、`-E`と外部cwdで実行した。
package・NumPy・SciPy・pandasがコピー先から読み込まれ、元repositoryが`sys.path`にないことを確認した。

| 確認 | 結果 |
|---|---|
| 非ゼロ差分復元 | 非学習点・負Iqでも既知差分磁束へ絶対2e-12 Wb以内 |
| prior固定 | 元モデル係数・stateが一致。コピーしたprior NPZは入力とbyte一致 |
| support／解析微分 | core・taper・outer外、q対称性、gauge不変、有限差分との一致を確認 |
| 保存復元 | final NPZ単体で全7評価量が保存前と完全一致 |
| コピー元の補正面 | 14点のW・磁束・Hessian全7量で最大差0 |
| コピー元の逆RBF | 17点のId／Iqで最大差0 |
| 公開LUT照合 | 順LUTは1公開単位以内、Aの逆2枚は31×31配列が完全一致 |
| 入力・失敗系 | 無効成分を局所除外、未観測qを不使用、範囲外・rank不足・逆Fit失敗・丸め重複・非上書きを確認 |
| 逆補間の範囲 | 凸包外節点・無効頂点を使う補間・領域外fallbackを有効往復へ含めない |

コピー元fixtureの条件と許容差は[fixtures/README](../tests/fixtures/README.md)を参照する。
本件で変更した独立packageとコピー元照合が検証対象。既存4component全suiteは実行しておらず、
「calibration全回帰PASS」とはしていない。

## 合成2モータの数値結果

AはI_base=100 A、Psi_base=0.12 Wb、3極対、1500 rpm。
BはI_base=40 A、Psi_base=0.035 Wb、7極対、−800 rpm。
両ケースとも補正用VI 165行→88観測（77ペア＋11単点）で、全88観測をFitへ使用した。
順LUTは25×17、逆LUTは31×31。表の残差はFitに使用した観測成分に対する値である。

| 指標 | モータA | モータB |
|---|---:|---:|
| 補正前 d残差RMSE [Wb] | 2.78539e-4 | 8.12405e-5 |
| 補正前 q残差RMSE [Wb] | 8.68254e-5 | 2.53241e-5 |
| 補正後 d残差RMSE [Wb] | 1.34778e-17 | 5.19101e-18 |
| 補正後 q残差RMSE [Wb] | 1.66298e-17 | 6.81363e-18 |
| Hessian最小固有値（順節点）[H] | 7.28571e-5 | 5.31250e-5 |
| 非正Jacobianの順LUT三角形 | 0 / 768 | 0 / 768 |
| 有効な逆LUT節点 | 571 / 961 | 571 / 961 |
| 磁束凸包外の逆節点 | 349 / 961 | 349 / 961 |
| 有効な往復評価点（節点＋セル中心） | 726 / 809 | 725 / 809 |
| 有効点のId往復RMSE / 最大絶対誤差 [A] | 0.331827 / 2.51628 | 0.128858 / 1.00646 |
| 有効点のIq往復RMSE / 最大絶対誤差 [A] | 0.0589352 / 0.521110 | 0.0219020 / 0.167441 |

補正残差が丸め誤差程度でも、有限格子のLUT往復誤差は残る。
特にtaper付近の曲率と公開格子の関係は、実データ用の格子設定で確認する必要がある。
Hessian／Jacobianが評価点で正であることや凸包内であることから、領域全体の逆写像の一意性や実測精度を保証しない。

## 実行と成果物

通常の再現コマンド（このフォルダを基準。出力先は空にするのではなく、必要なら別名へ変更する）:

```bash
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
.venv/bin/python run_fit_jmag.py --config examples/motor_a.toml
.venv/bin/python run_identify_flux.py --config examples/identify_correction_a.toml
.venv/bin/python run_build_maps.py --config examples/build_maps_a.toml
.venv/bin/python run_fit_jmag.py --config examples/motor_b.toml
.venv/bin/python run_identify_flux.py --config examples/identify_correction_b.toml
.venv/bin/python run_build_maps.py --config examples/build_maps_b.toml
```

最終確認では上記設定の`../output/`を`../output/stage3_validation/`へ置き換えた一時設定を使った。
実行したコマンド、作業ディレクトリ、終了コード、出力は以下の検証ログに記録した。

- [Aのsummary](../output/stage3_validation/maps_a/summary.json)、[最終面](../output/stage3_validation/maps_a/final_model.npz)、[補正残差](../output/stage3_validation/maps_a/correction_residuals.csv)、[往復誤差](../output/stage3_validation/maps_a/roundtrip.csv)
- [Bのsummary](../output/stage3_validation/maps_b/summary.json)、[最終面](../output/stage3_validation/maps_b/final_model.npz)
- [単体コピー・新規venvと最終コードの検証ログ](../output/stage3_standalone_validation.json)
- [実行・再開・出力確認のRUNBOOK](../RUNBOOK.md)

`output/`と`.venv/`はGit対象外。設定例・合成VI・テストfixture・本書から結果を再現できる。

## 残件と変更境界

工程表のWP0〜WP8はソフトウェア実装・合成データ確認の範囲で完了した。
次は対象の実JMAG／実測データとモータ条件を接続し、補正範囲、knot、正則化、順逆格子と残差を確認する。
実データ精度、Windows/Linux、大規模Fitの計算量は未確認。RBFは全順節点を使うため、大格子の計算量は保証しない。

変更は`coenergy_maps/`とcalibration入口・project listに限定した。
既存の`code_flux/`、実験・報告書・raw・golden・保存済み出力、base実装は変更していない。
この作業ではコミット・push・mergeを行っていない。
