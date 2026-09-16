# 工程①「JMAG面作成」実装結果と申し送り

2026-09-17。工程①の独立CLI実装と、合成VIによる実行確認を完了した。
本書は既存計画に基づくソフトウェア実装の結果であり、別モータの実データ精度や技術採用の判断ではない。

## 実装結果

`run_fit_jmag.py --config <TOML>`で、JMAG VI→点磁束同定→Co-energy Fit→保存面・点別残差まで実行できる。
①に必要な共通同定を使う`run_identify_flux.py`も実装し、工程②の点磁束保存までを利用可能にした。

- JMAG標準列と任意列対応を実装。指令座標の一致または明示pair_idで鏡像ペアを対応させる。
- 元行、ペア、観測成分、計算不能理由を保持。単点のq=0を観測値として重み付けしない。
- モータ別に極対数、抵抗、dq規約、電流・磁束スケール、定義域、knot、正則化、solver、積分を設定できる。
- 数値コアは`1b65b45`の`code_flux/coenergy_forward_fit.py`とbyte一致。実行時は独立packageだけをimportする。
- モデルはfloat64 NPZへ保存し、pickleを使わず再読込み可能。点磁束・残差は有効桁17桁のCSV。
- 非空出力先を保護し、後段のFit失敗時も点磁束・診断・理由を残す。
- calibrationの環境方針へ本フォルダ限定の例外を追記し、専用venvと依存定義を設けた。

成果物の説明と条件は[入力契約](input_output_contract.md)、実行方法は[RUNBOOK](../RUNBOOK.md)を正とする。
既存4component、レポート、run case、raw／golden、baseコードは変更していない。

## 実行・検証結果

macOS arm64、Python 3.13.7、NumPy 2.5.3、SciPy 1.18.1、pandas 2.3.3で確認した。
`pip check`は依存不整合なし。同梱の`unittest`は30件すべて成功（skipなし）。
内訳はコピー元から引き継いだ数値コア17件と、同定・CLI・保存・異常系・コピー実行13件。

実行コマンド（このフォルダを基準）:

```bash
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/python run_fit_jmag.py --config examples/motor_a.toml
.venv/bin/python run_fit_jmag.py --config examples/motor_b.toml
.venv/bin/python run_identify_flux.py --config examples/identify_flux.toml
```

| 確認 | 結果 |
|---|---|
| モータA | I_base=100 A、Psi_base=0.12 Wb、3極対、1500 rpm。221行→117観測、全点Fit使用 |
| モータB | I_base=40 A、Psi_base=0.035 Wb、7極対、−800 rpm。221行→117観測、全点Fit使用 |
| Aのd成分 | RMSE 1.91e-16 Wb、最大絶対残差1.01e-15 Wb（117成分） |
| Aのq成分 | RMSE 2.06e-16 Wb、最大絶対残差1.11e-15 Wb（104成分） |
| Bのd成分 | RMSE 9.45e-17 Wb、最大絶対残差4.13e-16 Wb（117成分） |
| Bのq成分 | RMSE 1.15e-16 Wb、最大絶対残差6.83e-16 Wb（104成分） |
| 数値診断 | 両ケースともspan_pass／optimality_pass=true |
| 保存・復元 | 復元モデルを非学習座標・負Iqで評価し、既知磁束・解析Hessianへ絶対2e-12以内 |
| コピー元照合 | 117点の同定と19点のW・磁束・Hessianをfixture照合。7評価量の実測最大差はいずれも0 |
| 失敗系 | 欠測、非有限、片側速度0、ペア欠落・重複、単点抵抗なし、定義域外、rank不足、出力非上書きを確認 |
| 独立コピー | `/private/tmp/`の空白を含む別フォルダに単体コピーし、新規venvを作成。30件テスト、2ケースの①、②がすべて成功 |
| import独立性 | PYTHONPATHを除去し`-E`で外部cwdからCLI実行。packageとNumPy／SciPy／pandasはコピー先から読み込み、元repositoryをsys.pathに含まない |

比較許容差は結果を見る前にテストへ定義した。コピー元fixtureの由来は
[fixtures/README](../tests/fixtures/README.md)に残した。
合成面は交差飽和項を持つ既知Co-energyから生成したもの。
残差が丸め誤差程度であることは、同定・接続・Fitの実装確認を意味し、実データの精度保証を意味しない。

実行成果物:

- [Aの保存モデル](../output/motor_a/prior_model.npz)、[設定](../output/motor_a/prior_settings.json)、[残差](../output/motor_a/fit_residuals.csv)、[summary](../output/motor_a/summary.json)
- [Bの保存モデル](../output/motor_b/prior_model.npz)、[summary](../output/motor_b/summary.json)
- [工程②の点磁束](../output/flux_samples/flux_samples.csv)
- [コピー先の検証コマンド・結果](../output/standalone_validation.json)

`output/`と`.venv/`はGit対象外。数値結果の要約は本書に残し、生成物は同梱設定とfixtureから再生成できる。
既存4componentのテストは変更対象外のため実行しておらず、calibration全回帰PASSとはしていない。

## 次工程への申し送り

1. 工程②のコードは利用可能。対象の学習用／実測VIを`examples/identify_flux.toml`へ接続する。
   モータ条件、dq規約、実測電流座標、鏡像ペア対応を確認し、点磁束・行診断を保存する。
   指令値の丸めずれや複数回取得があるときは、取得時の対応を明示pair_idへ入れる。
2. 工程③へ渡す①の資産は`prior_model.npz`、`prior_settings.json`、`jmag_flux_samples.csv`。
   ②の`flux_samples.csv`と成分mask／weightを引き継ぎ、priorを固定して差分Co-energyだけをFitする。
3. 工程③実装前に、補正基底・基準点・補正範囲・重み、順逆軸、CSVの向き・公開桁・補間契約を決める。
   `coenergy_prior_correction.py`の切り出し・積の微分・保存復元は未着手。WP2残件→WP5→WP6が次の実装順序。
4. 逆Fitは補正後の公開順LUT節点から作る。保存した面の矩形定義域と、観測座標の外接矩形、
   補正範囲、逆変換有効範囲を混同しない。後2者は現在のsettingsではnull。
5. 工程③完成後にWP7の①〜③通し確認とWP8の全RUNBOOKを完成させる。コミット・push・mergeは未実施。

未検証事項は実JMAG full data・実測入力での精度、Windows/Linuxの実行、大規模Fitの計算量。
本依頼では対象実データ一式が指定されていないため、同梱した合成2ケースで①を確認した。
現段階のFit仕様選定は明示設定のみであり、DENの候補探索や実データ向けのknot／正則化最適化は行っていない。
