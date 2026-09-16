# Co-energy面作成・点磁束同定・順逆マップ作成 RUNBOOK

工程①「JMAG面作成」、工程②「点磁束作成」、工程③「固定JMAG面の差分補正・順逆マップ作成」を実装済み。
入出力・数式・制約は[入力契約](design/input_output_contract.md)、確認結果と次工程への申し送りは
[工程①実装結果](design/stage1_implementation_result.md)と[工程③実装結果](design/stage3_implementation_result.md)を参照する。

## 1. フォルダと環境の準備

この`coenergy_maps/`フォルダだけをコピーする。`.venv/`と`output/`を除き、コピー先でvenvを作る。
NumPy・SciPy・pandas以外のライブラリ、元repository、既存の計測queueやreport設定は不要。
Python 3.11以上が必要。実行確認はmacOS arm64、Python 3.13.7で行った。

macOS／Linuxの例（初回だけ、利用するPython 3.11以上を選択）:

```bash
cd <copied-folder>/coenergy_maps
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
```

Windows PowerShellの例（未実機確認）:

```powershell
cd C:\work\coenergy_maps
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -q
```

実行確認環境はNumPy 2.5.3、SciPy 1.18.1、pandas 2.3.3。これは固定lockではなく確認時のversion。
別Python／OSでは、その環境用wheelをインストールしてテストを実行する。

## 2. 同梱例の実行

以下は合成VIによる動作例。JMAG実解析や実測の精度確認ではない。

```bash
.venv/bin/python run_fit_jmag.py --config examples/motor_a.toml
.venv/bin/python run_fit_jmag.py --config examples/motor_b.toml
.venv/bin/python run_identify_flux.py --config examples/identify_flux.toml
.venv/bin/python run_identify_flux.py --config examples/identify_correction_a.toml
.venv/bin/python run_build_maps.py --config examples/build_maps_a.toml
.venv/bin/python run_identify_flux.py --config examples/identify_correction_b.toml
.venv/bin/python run_build_maps.py --config examples/build_maps_b.toml
```

Windowsでは先頭を`.\.venv\Scripts\python.exe`へ置き換える。
それぞれ`output/motor_a/`、`output/motor_b/`、`output/flux_samples/`へ保存される。
prior例は221行から117観測（104ペア＋13単点）を作る。
補正用の②は165行から88観測（77ペア＋11単点）を`output/correction_a/`または`correction_b/`へ保存する。
③は対応する保存priorと点磁束を読み、`output/maps_a/`または`maps_b/`へ保存する。
合成補正VIの既知差分式と再生成方法は`examples/generate_correction_examples.py`に記載した。

同じ設定を再実行すると非空出力先を保護するため停止する。既存出力を削除する必要はない。
TOMLの`output.directory`を別の空ディレクトリへ変更する。
起動ディレクトリを変えても、入出力pathはTOMLの場所から解決される。

## 3. 自分のJMAG VIから工程①を実行

1. `examples/motor_a.toml`を別名でコピーし、`input.csv`と`output.directory`を設定する。
2. VIのdq単位・符号、鏡像ペアの取得条件を[入力契約](design/input_output_contract.md)と照合する。
   電力不変／振幅不変は宣言だけであり、RMSやabcから自動換算しない。
3. 標準列でなければ`input.columns`を設定する。列対応の全指定は`motor_b.toml`を参照する。
   鏡像ペアが正確な指令座標で結べない場合、または同じ座標を複数回取得した場合は明示的な`pair_id`を用意する。
4. `pole_pairs`、必要なら単点用の抵抗、温度を設定する。mirror pairだけなら抵抗は省略可能。
5. `fit`の電流・磁束スケール、u/vのknot、正則化、solver、積分次数を選ぶ。
   DEN専用の自動選定はなく、同梱値は実機推奨値ではない。
6. `run_fit_jmag.py --config <作成したTOML>`を実行する。

まず`summary.json`のstatus、計算可能数、Fit使用数、成分別RMSE／最大残差、数値診断を確認する。
`input_diagnostics.csv`で元行とペアの理由を、`fit_residuals.csv`で位置別の誤差を確認する。
単点のq残差空欄は、q磁束を観測として使わないためである。
速度差と鏡像電流差は計算を止める閾値ではなく、同定式の前提からのずれを判断する材料になる。

## 4. 保存面の再読込みと工程②

保存したNPZの連続評価は次のように呼ぶ。これはAモータ例の定義域内の座標。

```python
from coenergy_maps import load_model

model = load_model("output/motor_a/prior_model.npz")
value = model.evaluate(id_A=[-50.0, 0.0], iq_A=[20.0, -20.0])
print(value.psi_d_Wb, value.psi_q_Wb)
print(value.l_dd_H, value.l_dq_H, value.l_qd_H, value.l_qq_H)
```

定義域外の評価はエラーになる。NPZと`prior_settings.json`、`jmag_flux_samples.csv`を一緒に残す。
矩形定義域は観測済み連続領域ではなく、補正範囲や逆変換の有効範囲も保証しない。

工程②は`examples/identify_flux.toml`を基にVI・モータ条件・列対応を設定し、
`run_identify_flux.py --config <TOML>`を実行する。①と同じ同定処理を使い、Fit設定とpriorは不要。
後続へ渡すのは`flux_samples.csv`と`input_diagnostics.csv`、その取得条件を記録した`run_settings.json`。
実測でインバータ電圧誤差や速度差が残る場合の精度・補償は今回検証していない。

## 5. 計算不能・Fit失敗時

- 欠測、非有限値、ゼロ速度、ペア不成立は当該観測のreasonへ保存する。他の観測は続ける。
- 単点で抵抗がない場合、その単点だけを除外する。
- 定義域外の点は`fit_used=false`で保持する。
- Fit失敗時にも生成済み点磁束・入力診断を残し、`summary.json`に理由を保存する。
- 数値診断warningがあっても生成したモデル・残差は残す。終了コード2を見て診断内容を確認する。
- 列欠落など正規化前のエラーは、計算に入れない理由を表示する。出力先確保後ならsummaryにも残す。

精度が悪いことだけを理由に成果物を削除しない。現在のFit設定と観測の分布を確認してから、
次の設定は別出力先で実行する。過去の残差を同一設定の結果として読み替えない。

## 6. 自分の保存面・点磁束から工程③を実行

1. `examples/build_maps_a.toml`をコピーし、①のNPZ・settings・点磁束と②の点磁束のpathを指定する。
   同じモータとdq規約の組であることを確認する。入力pathは設定の場所から解決される。
2. `correction.fit`へ差分面のknot・スケール・正則化を設定する。少数点に対して自由度が大きすぎるとrank不足になる。
3. `correction.support`で補正に使うcore、滑らかにpriorへ戻すouter、Co-energyの基準電流を指定する。
   core外の観測は理由付きで保存し、Fitには使わない。outerはpriorと差分面の両方の定義域内に置く。
4. 順電流軸、逆磁束軸を節点配列で指定する。q軸は0始まり。逆軸は6桁へ丸めても節点が重複しないようにする。
   磁束軸が広いと外挿節点が増える。外挿値も残すが、有効範囲へ数えない。
5. `smoothing_d`と`smoothing_q`を明示し、空の出力先を指定して実行する。

```bash
.venv/bin/python run_build_maps.py --config <設定TOML>
```

①・②の保存成果物だけから開始でき、元VIの再同定は不要。③の設定変更は別の出力先で実行する。
逆Fitに失敗した場合も、`summary.json`の`failed_step`と理由、`completed_steps`、保存済みの最終面・順LUTを確認できる。
修正した設定で③を再実行する際も別出力先を使う。既存の成果物を削除してやり直す必要はない。

| 出力 | 確認内容 |
|---|---|
| `final_model.npz` / `final_settings.json` | prior・差分・supportを同梱した連続面、定義域と公開条件 |
| `correction_samples.csv` | 元観測、成分maskと無効理由、core内外、使用行 |
| `correction_residuals.csv` | 同じ観測に対するprior／補正後の残差。未観測qは空欄 |
| `forward_flux_map_psi_d.csv` / `forward_flux_map_psi_q.csv` | 行Iq・列Id、値Wb、小数8桁 |
| `inverse_fit_samples.csv` | 公開順LUT節点から作った逆Fit入力。生の実測点ではない |
| `inverse_flux_map_id.csv` / `inverse_flux_map_iq.csv` | 行Psi_q・列Psi_d、値A、軸と値は小数6桁 |
| `inverse_validity.csv` / `inverse_domain.csv` | 磁束凸包内か、復元電流が順格子内か。0の節点は外挿等で利用範囲外 |
| `roundtrip.csv` | 節点・セル中心の面→順LUT差、順逆電流誤差、往復磁束誤差、逆RBF→逆LUT差とfallback |
| `summary.json` | 残差、Hessian／順LUT Jacobian、往復誤差の全点／有効点別集計、warningと失敗理由 |

モデルの再評価は①と同じAPIを使う。

```python
from coenergy_maps import load_model

model = load_model("output/maps_a/final_model.npz")
value = model.evaluate(id_A=[-50.0, 0.0], iq_A=[20.0, -20.0])
```

`final_model.npz`単体で復元できる。taper外では厳密にpriorへ戻る。
公開マップを読むときはDelaunay三角形の線形補間を用いる。領域外の最近傍fallbackは有効な逆変換として扱わない。
逆補間は凸包と格子の内側に加え、補間三角形の全頂点で`inverse_validity=1`であることを確認する。
負qではq対称性に従って入力・出力qの符号を反転する。

`COMPLETE`は処理の完了を意味し、精度や実機採用の判定ではない。順格子・逆格子の粗さ、taper位置、
補正点の密度によりLUT誤差は変わる。凸包も実測精度や逆写像の一意性を保証しない。
確認済みはmacOSの合成2モータ、49件のテスト、独立コピーの新規venv。
実JMAG／実測、Windows／Linux、大規模Fitは未確認であり、対象データで残差と有効範囲を評価する。
