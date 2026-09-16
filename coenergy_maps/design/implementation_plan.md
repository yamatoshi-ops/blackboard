# Co-energy磁束マップ作成コードの独立化 実装工程表

- 作成日: 2026-09-17
- 状態: 工程①〜③を実装済み。合成2モータで通し実行・コピー元照合・49件テスト・単体コピー実行を確認。
- 対象フォルダ: `features/calibration/coenergy_maps/`
- 調査した切り出し元: `main`の`1b65b45`時点の`features/calibration/code_flux/`
- 次の作業: 対象の実JMAG／実測VI、モータ条件、補正範囲・格子を接続し、残差と有効範囲を確認する。
- 工程①の実装結果・次工程への申し送り: [stage1_implementation_result.md](stage1_implementation_result.md)
- 工程③の実装結果: [stage3_implementation_result.md](stage3_implementation_result.md)
- 確定した①〜③の契約: [input_output_contract.md](input_output_contract.md)、実行手順: [RUNBOOK](../RUNBOOK.md)

## 1. 目的と対象範囲

Co-energy面Fitを使う磁束マップ作成処理を、他のモータでも設定と入力データを差し替えて
実行できる独立コードとして切り出す。利用者が実行する処理は次の3工程とする。

1. JMAGのVIデータからCo-energy面を作成する。
2. VIテーブル（学習用データ・実測データ）から点磁束テーブルを作成する。
3. 点磁束テーブルとCo-energy面から、磁束マップと逆磁束マップを作成する。

初版の工程③は、前回提示した「JMAG面を固定し、点磁束との差分をCo-energy面としてFitする」
構成を前提とする。点磁束だけから面全体を再Fitする別経路は、初版へ自動追加しない。
この前提を変更する場合は、工程③の入出力・実装対象・照合対象を実装前に本書へ反映する。

本件は既存処理の切り出しと実行経路の整備であり、レポートの問いや評価方法を変更する作業ではない。
差分補正には既存の数値コアと合成データによるテストがあるが、実データ用の接続処理は追加が必要である。
独立コードの動作確認と、別モータの実データに対する精度・実機適合性の確認を区別する。

## 2. 変更境界と独立性

### 2.1 変更するもの

- `coenergy_maps/`内の実装、設定例、テスト、設計文書、RUNBOOK。
- `project_list.md`の現在地と、calibrationの入口文書から本フォルダへの参照。
- 単体コピーして実行するために必要な、calibrationのPython環境方針への限定的な追記。

### 2.2 保護するもの

- `code_flux/`を含む既存componentのコード、テスト、設定、公開成果物schema。
- 既存の技術報告書、検証計画書、実験用runner、run case、rawデータ、golden、保存済み出力。
- `motor_simulation_base/`の実装と既定値。

既存コードを新フォルダへコピーして編集してよい。重複を許容し、既存レポート側を
新コードへ付け替えたり、共通ライブラリへ移して両者を同時に変更したりしない。

### 2.3 独立実行の条件

- 実行時のimportは、新フォルダ内のpackageと明記した外部Pythonライブラリだけに限定する。
- `code_flux/`等へのimport、親フォルダへの`sys.path`追加、動的読込み、シンボリックリンクを使わない。
- 既存レポート用の設定・manifest・計測queue・出力フォルダを実行必須入力にしない。
- 入出力の相対パスは設定ファイルの場所を基準に解決し、起動ディレクトリに依存させない。
- 面・設定・点磁束はファイルで受け渡す。保存した成果物だけで後続工程を再開できるようにする。
- コピー元との照合は開発時に行う。配布テストには必要な小規模fixtureを同梱し、元リポジトリを必要としない。

## 3. 3工程の入出力案

①〜③のファイル名、CLI、数値契約は[入力契約](input_output_contract.md)で確定し、実行できる。
③は固定priorへのC2 taper付き差分Co-energy補正、明示設定のRBF逆Fit、順8桁・逆6桁の公開LUTを採用した。

| 実行工程 | 入力 | 処理 | 主な出力 |
|---|---|---|---|
| ① JMAG面作成 | JMAG VI CSV、モータ条件、同定条件、Fit設定 | VI正規化、点磁束同定、Co-energy Fit、モデル保存 | `jmag_flux_samples.csv`、`prior_model.npz`、`prior_settings.json`、点別Fit残差 |
| ② 点磁束作成 | 学習用または実測VI CSV、モータ条件、同定条件 | VI正規化、点磁束同定、計算可否と元行対応の保存 | `flux_samples.csv`、入力診断表 |
| ③ 順逆マップ作成 | ①の保存面、②の点磁束、補正設定、順逆マップ軸 | 差分Co-energy Fit、最終面の評価、順LUT化、逆Fit、CSV保存 | 補正後モデル一式、順逆マップ4枚、有効範囲、残差・往復誤差 |

①と②の磁束同定は、新フォルダ内で同じ処理を利用する。①はVIからCo-energy面までを一度に実行し、
途中の点磁束も保存する。②は点磁束の保存で終了し、Co-energy面を必要としない。

点磁束の数値列は`id_A`、`iq_A`、`psi_d_Wb`、`psi_q_Wb`を中心とし、元行またはペアの対応、
観測できた成分、計算不能理由を保持する。`Iq=0`で対称性から置いた`psi_q=0`を実測値として重み付けしない。
具体的な列名と型はWP1で確定する。

工程③はCo-energyの差分を補正し、その微分から磁束を作る。補正範囲に重みを付ける場合も、
既存コアのCo-energyに対する処理と積の微分を引き継ぐ。逆マップ用の磁束・電流対応は、補正後の
最終面から生成した公開順LUTの節点を出発点とする。生の点磁束から別の逆マップを同時に作る経路は設けない。

順マップの出力名は`forward_flux_map_psi_d.csv`、`forward_flux_map_psi_q.csv`、
逆マップは`inverse_flux_map_id.csv`、`inverse_flux_map_iq.csv`を基本とする。
軸の向き、単位、丸め、補間、適用範囲はWP1で定義し、既存CSVとの互換範囲を明記する。

## 4. 切り出し元と必要な変更

| 機能 | 主な参照元 | 新コードで行うこと |
|---|---|---|
| VI入力変換 | [measurement_io.py](../../code_flux/measurement_io.py)、[dense_jmag_rt_flux_identification.py](../../code_flux/dense_jmag_rt_flux_identification.py) | 必要なCSV adapterと列変換をコピーし、実験用view・queueから分離する |
| 点磁束同定 | [identification.py](../../code_flux/identification.py)、[dense_jmag_rt_flux_identification.py](../../code_flux/dense_jmag_rt_flux_identification.py) | 同定式、ペア対応、使用電流座標、計算不能行の処置を引き継ぐ |
| Co-energy Fit | [coenergy_forward_fit.py](../../code_flux/coenergy_forward_fit.py) | 数値コアをコピーし、package内だけでimportできる形にする |
| Fit設定・積分点・モデル保存 | [coenergy_report2.py](../../code_flux/coenergy_report2.py)、[coenergy_full_fit.py](../../code_flux/coenergy_full_fit.py) | 必要な処理を取り出し、DEN専用の電流・格子・識別名を設定へ分離する |
| JMAG面の差分補正 | [coenergy_prior_correction.py](../../code_flux/coenergy_prior_correction.py) | 補正コアをコピーし、設定読込み、点磁束接続、モデル保存・復元を追加する |
| 順LUTから逆マップへの接続 | [coenergy_capacity_ladder.py](../../code_flux/coenergy_capacity_ladder.py)の`build_capacity_artifact_chain()` | マップ生成に必要な接続だけを取り出す |
| 逆Fit・マップ評価 | [inverse_fit.py](../../code_flux/inverse_fit.py)、[flux_map_model.py](../../code_flux/flux_map_model.py) | 必要なRBF逆Fit、領域判定、補間、往復評価をコピーする |
| 出力 | [output.py](../../code_flux/output.py) | 必要なCSV書式・非上書き処理を取り出し、新しい成果物writerにまとめる |

既存の`config.py`、`output.py`、逆Fit周辺をそのままimportすると、別のFit方式やトルクQAなどの
依存も入る。コピー時に必要な型・関数を整理し、レポート用pipeline全体は持ち込まない。
容量比較、24条件比較、選点探索、報告書作図、Cテーブル生成は今回の実行処理に含めない。

## 5. モータ別設定と適用前提

WP1では少なくとも次を設定または入力契約として明示する。

- VI列対応、単位、dq変換の規約、電流・電圧の振幅基準、回転速度と符号、極対数。
- ペアの対応方法、実測電流による代表座標、ゼロ速度・欠測・非有限値の扱い。
- 同定式で必要になる場合の抵抗と温度条件。mirror pairと`Iq=0`単点で必要条件を分ける。
- Fitの基準電流・磁束スケール、定義域、基底・knot、正則化、数値解法、積分点。
- JMAG面の仕様選定方法。現行の選定処理を用いる場合は、DEN専用格子に依存する分割規則も設定へ分離する。
- 差分補正の基底、補正範囲、基準点、点磁束の成分mask・weight。
- 順マップの電流軸、逆マップの磁束軸、公開精度、逆Fit条件。

初版は既存コアと同様、`Id, Iq`で表す定常磁束とq軸鏡像対称性を前提とする。
温度などの別軸を持つモデルや、非対称な面への拡張は追加しない。
同定は既存のmirror pair方式を第一候補とし、対応するVI形式と取得条件をWP1で確定する。
既存のmulti-speed方式は、初版入力に必要と分かった場合に限り実装範囲へ追加する。

DENの基準電流、最低電流範囲、12.5 A／25 A格子、固定view名を汎用の既定値にしない。
モデルの矩形定義域、データで確認できる範囲、補正範囲、逆変換が利用可能な範囲を区別して保存する。
Co-energy面であることだけから、逆変換の一意性や実測精度を保証しない。

## 6. 配置と実行環境

実装済みの構成は次のとおり。3つのCLIをフォルダ単体で実行できる。

```text
coenergy_maps/
├── design/
│   └── implementation_plan.md
├── RUNBOOK.md
├── requirements.txt
├── .gitignore
├── run_fit_jmag.py
├── run_identify_flux.py
├── run_build_maps.py
├── coenergy_maps/        # 計算コア・設定・入出力
├── examples/             # 設定例・小規模な合成VIデータ
└── tests/
```

Pythonは既存のTOML読込みに合わせて3.11以上を基本とし、実際に確認したversionをRUNBOOKに記載する。
数値処理の主要依存候補はNumPy、SciPy、pandas。診断図を出す場合のMatplotlibなど、採用する依存はWP1で絞る。

フォルダ単体で配布するため、`coenergy_maps/requirements.txt`と`coenergy_maps/.venv/`を持つ。
これは[calibrationの共有環境方針](../../AGENTS.md#python環境)に対する、本フォルダ限定の例外として
同AGENTS.mdとREADME.mdへ追記済み。既存4componentの環境・依存定義は変更しない。
venvと生成出力はGit管理対象外とし、別PCではvenvを作り直す。

## 7. 実装工程表

実行工程①〜③と実装順序は区別する。①でも使う共通同定処理を先に作るため、CLI②を先に完成させる。
各WPの成果物・確認結果・残件はこの表へ更新する。コミット、push、mergeは個別の依頼時に行う。

| WP | 依存 | 実装内容 | 成果物・完了確認 | 状態 |
|---|---|---|---|---|
| WP0 | なし | フォルダ作成、切り出し調査、実装工程表の作成 | 本書とproject listから着手位置を参照できる | 完了 |
| WP1 | WP0 | VI形式、同定方式、3工程のschema・CLI、モータ設定、領域と丸め、環境を定義 | 設定例と入出力仕様、独立環境の限定例外を記録。RUNBOOKの構成を用意する | 完了。③のsupport・明示Fit・正半面軸・順8桁／逆6桁・補間と有効範囲を実装前に固定 |
| WP2 | WP1 | Co-energy Fit、補正、積分点生成、モデル保存・復元の部品をコピー | package内だけでimportできる。同一入力でコピー元とFit・微分値が整合し、保存後に再評価できる | 完了。補正コアと積の解析微分を抽出。prior／delta／supportを同梱保存し、全7評価量の復元を確認 |
| WP3 | WP1 | 共通VI adapter・点磁束同定・CLI②を実装 | 学習用／実測用入力を点磁束へ変換できる。元行・ペア・観測成分・計算可否を追える | 初版実装完了。JMAG列／任意列対応、合成2ケース・計算不能診断を確認。実測適合は未確認 |
| WP4 | WP2、WP3 | JMAG VIからCo-energy面を作るCLI①を実装 | JMAG相当VIから保存面と点別残差を生成できる。モータ範囲・Fit条件が設定に従う | 完了。各221行→117観測、保存面・点別残差を生成 |
| WP5 | WP2、WP3、WP4 | 点磁束による差分補正と、最終面・順LUTの保存を実装 | 固定priorを保持して補正できる。補正範囲・残差を保存し、最終面の再読込み結果が整合する | 完了 |
| WP6 | WP5 | 逆Fit・逆LUT・有効範囲・往復評価を接続し、CLI③を完成 | 最終順LUTを起点に順逆4マップが揃う。逆Fit失敗時にも生成済み面・順LUT・理由を残す | 完了 |
| WP7 | WP4、WP6 | 数値照合、モータ設定変更、単体コピー実行を検証 | 同梱テスト全件と①〜③の通し実行が成功する。コピー先から元リポジトリを参照しない | 完了。49 tests PASS。コピー元の補正面・逆RBFと数値一致、A公開逆LUT完全一致。新規venvの単体コピーで2モータ①〜③が成功 |
| WP8 | WP7 | 実行済みコマンドでRUNBOOKを完成し、現在地を更新 | 利用者が入力を準備し、①〜③の実行・再開・出力確認を行える。実データ・OS別の未検証事項を明記する | 完了。①〜③の実行・再開・出力・制約をRUNBOOKと実装結果へ反映 |

## 8. 検証方法

### 8.1 コピー元との数値照合

- 同一の小規模入力と設定で、点磁束、Co-energy面の磁束・Hessian、差分補正、順逆LUTを照合する。
- 浮動小数点値は演算・公開精度に応じた許容差で比較し、軸・列の意味・行対応を別に確認する。
- 照合条件は結果を見る前にテストへ定義する。差が出た場合は許容差を広げて済ませず、設定・演算・丸めの段階を切り分ける。
- コピー元の実験出力・goldenは上書きせず、一時出力先を使う。

### 8.2 独立コードとしての確認

- 基準電流・極対数などが異なる2ケースの合成VIを使い、コード編集なしで設定を切り替える。
- 既知面に対する点磁束同定、既知の差分面の補正、q軸対称性、補正範囲、保存モデルの復元を確認する。
- 入力の欠測・ペア不成立・ゼロ速度を位置と理由付きで記録する。計算可能なデータまで一律に失わない。
- 順LUTと連続面の差、順逆変換の往復誤差、逆Fitの外挿域を区別して確認する。
- 新フォルダだけを一時ディレクトリへコピーし、専用venvを作成して①〜③を実行する。
  `PYTHONPATH`、作業ディレクトリ、設定、テストfixtureからコピー元を参照していないことも確認する。
- 同梱する`unittest`全suiteを実行する。既存componentを変更しない場合は、新コードと必要なコピー元照合を対象とし、
  未実行の既存4componentを含めて「calibration全回帰PASS」と表現しない。

実測VIとJMAG実データが利用可能なら、それぞれの対応adapterで追加確認する。
実行できない場合は合成データでの確認範囲を明記し、実データ適合を確認済みと扱わない。

## 9. RUNBOOKに残す内容

RUNBOOKはWP1で構成を作り、各CLIの実装時に手順を追記し、WP8で実行結果と照合する。

1. 対応するモータ・VI取得条件、必要列、単位、dq規約とペア構成。
2. フォルダのコピー、Python選択、専用venv作成、依存インストールと確認。
3. 設定例を別モータへ変更するときの項目と、①〜③の入力・出力の対応。
4. ①JMAG面作成、②点磁束作成、③順逆マップ作成の具体的なコマンド。
5. 点別残差、連続面とLUTの差、有効範囲、補正範囲、往復誤差の確認方法。
6. 保存面・点磁束からの再開、非空出力先の保護、計算不能行、Fit／逆Fit失敗時の成果物の所在。
7. macOS/LinuxとWindowsのパス・venvコマンド。実際に実行したOSと未検証OSを区別する。

## 10. 現在地

2026-09-17、工程①〜③のソフトウェア実装と合成データによる確認を完了した。
工程①・②は開始時点のcommit `56a6615`で実装済みで、今回の変更前に既存30 testsを再実行して成功した。
工程③ではWP2の補正コア残件、WP5〜WP6の保存面・順逆マップ、WP7〜WP8の検証・文書を完了した。
現在の同梱suiteは49 tests PASS。合成2モータ、コピー元との数値照合、独立コピーの新規venvによる
①〜③の通し実行を確認した。数値結果と成果物は[工程③実装結果](stage3_implementation_result.md)を参照する。

残件は実JMAG full data、実測入力、Windows/Linux、大規模Fitの性能と実データ用設定の確認。
実装完了は実機適合や技術採用の判断ではない。既存の実験コード・成果物・baseは変更していない。
本作業でのコミット・push・mergeは行っていない。
