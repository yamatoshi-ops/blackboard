# 工程①〜③の入出力契約 v1

2026-09-17。①・②の契約を維持し、③の実装前に補正・公開マップ契約を追記した。

## VI入力

定常dq量を1運転点1行で与える。時間波形の平均化、abc→dq変換、RMSからの換算はこのコードでは行わない。
電流はA、電圧はV、速度は機械rpm、磁束はWb、抵抗はΩ。d/q電流・電圧には同じ変換規約を使い、
`motor.dq_convention`に`power_invariant`または`amplitude_invariant`を宣言する。
この文字列は換算指示ではない。q軸は`vd=R*id-ωe*ψq`、`vq=R*iq+ωe*ψd`の符号を使う。
`ωe=pole_pairs*2π*rpm/60`。負回転も符号付きで計算する。
元データがphase RMS、線間電圧、別dq規約の場合は、入力を変換してから渡す。

`input.format="jmag_vi"`の標準対応は以下。元の13列VIのうち計算に使わない列は必須にしない。

| 正規列 | CSV列 | 意味 |
|---|---|---|
| source_no | PTN_No | 元番号。重複可、対応の主キーには使わない |
| rpm | RPM_moni | 符号付き機械速度 |
| id_ref_A / iq_ref_A | Idref_moni / Iqref_moni | ペア対応に用いる指令座標 |
| id_A / iq_A | Id0_1st / Iq0_1st | 実測dq電流 |
| vd_V / vq_V | Vd_1st / Vq_1st | 定常dq電圧 |

`input.columns`で列名を変更できる。`mapped_dq`では列対応をすべて明示する。
任意の`pair_id`を指定した場合はその値でグループ化し、同じgroup内の`iq_ref_A`符号で＋／−を決める。
その場合`id_ref_A`は必須でなく、`source_no`省略時は0始まり元行番号を使う。

pair_idを指定しない場合は、`(id_ref_A, abs(iq_ref_A))`の完全一致で対応する。
各groupは「正負1行ずつ」または「iq_ref_A=0の1行」でなければ計算しない。
複数速度・反復取得・指令値の丸めずれがあるデータは、取得時に確定した対応を`pair_id`として入力する。
JMAG出力の`PairID`という列名だけでは真の鏡像対応を意味するとは限らないため、自動対応には使わない。
最近傍の実測電流や速度からペアを推測しない。

文字列はUTF-8 BOMあり／なしを標準とし、`input.encoding`で変更できる。
行番号`source_row_index`はヘッダを除くCSVレコードの0始まり。CSV列の欠落は列名付きエラーとし、
個別値の非数値・欠測・非有限は診断表へ残す。

## 同定式と使用座標

鏡像ペアは同じ速度・同じ温度条件、Id一致、Iq符号反転、磁束のq鏡像対称性を前提とする。
既存コアの式を引き継ぎ、正Iq指令側をp、負側をnとすると、

```text
ωe = pole_pairs * 2π * rpm_p / 60
id = (id_p + id_n) / 2
iq = (iq_p - iq_n) / 2
ψd = (vq_p + vq_n) / (2ωe)
ψq = (vd_n - vd_p) / (2ωe)
```

実測座標が負Iqになる場合は、q対称性によって`iq`と`ψq`の符号を同時に反転して正半面へ畳み込む。
抵抗はペア式には適用しない。電流差・速度差による誤差を補償しているわけではない。
`rpm_difference`、`mirror_id_difference_A`、`mirror_iq_sum_A`を保存し、差の大きさだけでは除外しない。
片側でも速度0または必要値が非有限の場合は、そのgroupだけを計算不能として記録する。

Iq=0指令単点は`ψd=(vq-R*iq_achieved)/ωe`でd成分だけを観測する。
抵抗が未指定の場合は単点だけを計算不能とし、ペアは計算する。
温度と抵抗の基準温度は設定へ記録できる。温度換算は行わず、取得条件に対応する抵抗を与える。
評価座標は`(id_achieved, abs(iq_achieved))`とし、残留q電流を`single_iq_achieved_A`へ保存する。
`ψq=0`を保存しても常にqのmask=false、weight=0とする。実測Iqも厳密に0のときだけ
`psi_q_structural=true`とする。残留Iqを0座標へ投影しない。

## 点磁束と診断表

①は`jmag_flux_samples.csv`、②は`flux_samples.csv`。1観測groupにつき1行とし、計算不能groupも残す。

- `id_A, iq_A, psi_d_Wb, psi_q_Wb`: float64相当、CSVは有効桁17桁。
- `observation_id, source_row_indices, source_nos`: 対応。複数行は`;`区切り。元番号は表示補助。
- `observation_type, status, reason`: ペア／単点／未解決と計算結果。
- `psi_d_observed, psi_q_observed, psi_q_structural`: boolean。保存値の有無と観測した事実を分離。
- `weight_d, weight_q`: 観測成分1、未観測0。Fit時に使用観測数nで割って平均損失にする。
- 前節の電流／速度診断値、`resistance_applied`を保存する。
- ①は`fit_used, fit_reason`を追加し、矩形定義域外の点を削除せず区別する。

`input_diagnostics.csv`は入力1行につき1行。正規化値、元行番号、観測group、status、reasonを持つ。
計算できるgroupを残した結果、点数が不足してFitのrankが成立しない場合はFitが失敗する。
その場合も点磁束と入力診断、`summary.json`の理由が残る。

## Co-energy面とFit

数値コアは`code_flux/coenergy_forward_fit.py`（`1b65b45`）のコピー。現行コードへの実行時依存はない。
3次tensor B-splineと低次成分を使い、q対称性・gauge・低次span除去・solverを引き継ぐ。
設定選定は`selection="explicit"`のみ。DEN固有の格子・下限・候補探索は持ち込まない。

`u=id/I_base, v=abs(iq)/I_base`。`u_breakpoints`と`v_breakpoints`が面の矩形定義域を定め、
vは厳密な0始まり。`i_base_A`、`psi_base_Wb`、knot、正則化、solver、許容値をTOMLへ明示する。
積分点は各knot span内のGL4またはGL8、重みは無次元面積Jacobianを含む。support、span、gauge、
roughnessの積分に同じ点を用いる。より広い空間へ外挿しない。
`dense_gelsd`または`sparse_lsmr`を選べ、後者は`solver_tolerance`と`solver_max_iterations`が必要。
疎solverでもコアの行列組立て・rank診断はdenseなので、大格子の省メモリは保証しない。

目的関数は観測された成分の`(ψfit-ψobs)/Psi_base`の二乗和/n＋設定した正則化。
同梱のゼロ正則化は既知面の復元例であり、実データ向け推奨値を決めたものではない。

| 成果物 | 内容・後工程での利用 |
|---|---|
| prior_model.npz | 全モデルstate、float64、pickle不使用。単独で連続面を再評価できる |
| prior_settings.json | schema v1、モータ、Fit条件、積分、矩形定義域、観測座標の外接矩形、対称性 |
| jmag_flux_samples.csv | 元観測、成分mask、使用座標を後工程へ引き渡す |
| fit_residuals.csv | 全観測とFit使用可否、W、予測磁束、符号付きfit−観測残差 |
| summary.json | 処理件数、除外、成分別RMSE／最大残差、数値診断、完了／失敗理由 |
| run_settings.json | 実行設定、解決した入力path、使用ライブラリversion |

観測点の外接矩形は検証済み連続領域を意味しない。採用する補正範囲・逆変換有効範囲は未決定（null）。
Co-energy面であることから逆写像の一意性や実測精度を主張しない。
残差は使用された観測成分だけで計算し、単点のq残差は空欄にする。

## CLI・工程③への接続

①`run_fit_jmag.py --config <TOML>`、②`run_identify_flux.py --config <TOML>`。
入出力の相対pathはTOMLの親から解決する。非空出力先は上書きせず、別の空ディレクトリを指定する。
終了コード0=完了、1=入力／Fit等の失敗、2=数値診断warningまたは観測0。2でも生成済み成果物は残す。

工程③は`prior_model.npz`、`prior_settings.json`、①の観測座標とmask、②の`flux_samples.csv`を入力とし、
固定priorへの差分Co-energyだけをFitする。①・②のNPZ／JSON／CSVを丸め直さず引き継ぐ。
③は`run_build_maps.py --config <TOML>`。設定例は`examples/build_maps_a.toml`と`build_maps_b.toml`。

## 工程③の固定契約

処理構造は「保存prior＋②の観測 → 差分Co-energy Fit → 合成連続面 → 公開順LUT → RBF逆Fit → 公開逆LUT」。
base制御・既存componentへの変更や接続はない。①の観測は由来・範囲の保存だけに使い、差分solveへ混ぜない。

`input`へ`prior_model`、`prior_settings`、`prior_samples`、`flux_samples`を明示する。
②と①のモータ・dq規約が同じことを利用者が確認して入力する。raw VIを③へ直接渡さない。
`correction.fit`は①のfitと同じ設定形式。`correction.support`はIdのouter/core、abs(Iq)のouter/core、
基準電流点をA単位で指定する。coreは重み1、outerまでC2 quinticで減衰し、outerの外は厳密に0。
補正は`W_final = W_prior + w(i) * (delta_W(i) - delta_W(i_ref))`。
磁束とHessianは積の微分を含む既存コアの解析微分。q鏡像対称性を保持する。

観測はcore内だけを補正Fitへ使う。非有限値・無効weightは成分別に無効化し、観測mask=falseの値は使わない。
計算不能、定義域外、core外、観測成分なしの行は理由付きで残す。負Iqはq磁束と同時に反転して正半面へ畳み込む。
損失は有効行数で割った成分weightを使う。単点q=0を学習観測へ変えない。
少数点でrank不足ならFit失敗を記録する。knotや正則化は自動で変更しない。

`forward.id_axis_A`と`forward.iq_axis_A`、`inverse.psi_d_axis_Wb`と`inverse.psi_q_axis_Wb`は
`[min, max, count]`ではなく節点値の配列。いずれも有限・厳密昇順、q軸は0始まりの正半面とする。
順軸は指定値を保持し、磁束値を小数8桁に丸める。逆軸は小数6桁に丸めてから評価し、電流を6桁に丸める。
丸めで逆軸の節点が重複する場合は逆工程だけ失敗し、順LUTと最終面は残る。
CSVは列がd軸、行がq軸。順CSV左上は空、逆CSV左上は`pq\pd`。単位は順軸A・値Wb、逆軸Wb・値A。
既存CSVと軸向き・値の桁数を揃えるが、モータ固有の格子・平滑化選定や全pipelineとの同値性は主張しない。

逆Fitは公開順LUTの節点を全て使う。既存コアの正規化thin-plate-spline RBF（degree=1）を用い、
`smoothing_d`・`smoothing_q`を明示し、入出力の標準偏差はddof=0とする。CV・近接点mergeは追加しない。
公開丸めで同じ磁束に異なる電流が対応する場合は逆Fitを停止する。負のq磁束を正半面へ無条件に反転して
異なる枝を混ぜず、逆Fit不成立として保存する。Iq=0境界の逆電流qは0に固定する。

公開LUTの評価はコピー元と同じDelaunay三角形の線形補間＋領域外最近傍fallback。
負q入力はq対称性で評価する。有効範囲は順LUTの矩形、逆学習磁束の凸包、逆LUTの矩形と
凸包内節点maskを区別する。凸包は実測済み領域や一意性の証明ではない。
逆補間の有効判定は補間三角形の全頂点が有効であることも確認する。外挿値はCSVへ保存するがmask=false。
最終面のHessian最小固有値と順LUT三角形のJacobian符号を診断し、非正値はwarningとして残す。

最終成果物は`final_model.npz`（prior・delta・supportを全て同梱）、`final_settings.json`、
`correction_samples.csv`、`correction_residuals.csv`、順逆4枚、`inverse_validity.csv`、
`inverse_fit_samples.csv`、`roundtrip.csv`、`summary.json`。①の設定・観測も出力先へコピーする。
`roundtrip.csv`は順節点と全セル中心で連続面→順LUTの差、順→逆の電流誤差、順→逆→順の磁束誤差、
RBFと公開逆LUTの差を分けて記録し、fallbackを使わない有効点だけの集計を別に出す。
終了コードは0=完了、1=入力／補正／逆Fitの失敗、2=完了したが数値・逆変換診断にwarning。
失敗時にもそれまでの保存面・順LUT・行診断・理由を残し、非空出力先を上書きしない。

確認条件は既知差分面の復元（磁束2e-12 Wb以内）、taperの有限差分との整合（Hessian 2e-8 H以内）、
保存復元の全7評価量一致、コピー元fixture（rtol=2e-11、atol=2e-12）、異なる2モータの通し実行、
丸め・mask・逆失敗時の成果物保持、フォルダ単体コピー実行とする。往復誤差は実測値を報告し、
実機採用の合否閾値へ読み替えない。
