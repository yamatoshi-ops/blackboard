2026年9月号（IEEJ JIA Vol.15 No.5）は、あなたにとって**かなり当たりの号**です。モータ制御だけでなく、センサレス、PWM、瞬時電圧制御、電力フィードバックという、現在のテーマにつながる論文が複数あります。

## 今月の優先順位

|     優先 | 文献                                                                                              |  おすすめ | 読み方     |
| -----: | ----------------------------------------------------------------------------------------------- | :---: | ------- |
|  **1** | **Enhanced Extended-EMF-Based PMSM Sensorless Control Using Oversampling**                      | ★★★★★ | **精読**  |
|  **2** | **Modulation Signal Optimized Synchronous PWM**                                                 | ★★★★★ | **精読**  |
|  **3** | **A Control-Oriented Approach to Power Balance Compensation in Bidirectional DC-DC Converters** | ★★★★★ | **精読**  |
|  **4** | **Rapid-Response Load-Side Acceleration Control... Sliding-Mode Torsion-Torque Servoing**       | ★★★★☆ | 精読      |
|  **5** | **Digital Closed-Loop Dead-Time Minimization...**                                               | ★★★★☆ | 要点精読    |
|  **6** | **Experimental Evaluation of... Series-Resonant PMSG... by THD**                                | ★★★☆☆ | 拾い読み    |
|  **7** | **Estimation of Differential Current... Using Gaussian Process Models**                         | ★★★☆☆ | 拾い読み    |
|  **8** | **Novel Free-Piston Engine Generator... Variable Frequency Control**                            | ★★★☆☆ | 興味があれば  |
|  **9** | **Analysis and Wide-Range Output Power Characteristics of Three-Phase SR-SAB**                  | ★★★☆☆ | コンバータ枠  |
| **10** | **Advantages of... Secondary-Resonant SAB DC-DC Converter**                                     | ★★☆☆☆ | #9とセット  |
|     11 | Weight Reduction of Multiterminal DC Interruption... Aircraft                                   | ★★☆☆☆ | 斜め読み    |
|     12 | Unidirectional 3-Phase AC/DC... SDBC                                                            | ★★☆☆☆ | 今回は後回し  |
|     13 | Functional Mode-Based Cooperative Transport                                                     | ★★☆☆☆ | 制御一般として |
|     14 | Non-Resonant Direct AC-AC Converter...                                                          | ★☆☆☆☆ | 今月は見送り  |

特に**上位5本まで読めば、今月は十分に元が取れる**と思います。

---

# 1位：Enhanced Extended-EMF-Based PMSM Sensorless Control Using Oversampling

### ★★★★★ 今月の最重要

これは迷わず読んでよいです。

通常のEEMFセンサレスでは、低速になるとEEMF自体が小さくなり、S/N悪化によってPLLなどの帯域を上げにくくなります。本論文は、**PWM周期内で電流をoversamplingし、モデル化したインバータ電圧と組み合わせてEEMFを推定する**構成です。実験では低速の急峻な負荷変動時に過渡角度誤差を43%低減しています。([J-STAGE][1])

あなたの場合、単に「センサレスだから」という以上に面白いです。

以前検討していた

> 電圧モデルの観測情報を増やせば推定性能は本当に上がるのか
> ノイズとモデルバイアスは別問題ではないか

という問題を、かなり具体的に考えられる論文だからです。

### 私ならここを読みます

特に、

**oversamplingによって何の情報量が増えているのか**

を追います。

PWM周期につき電流1点だったものをN点取得することで、

`di/dt → v - Ri - e`

の観測をPWM周期内部まで利用する考え方です。

ただし重要なのは、

> **oversamplingはS/Nを改善しても、インバータ電圧モデルの系統誤差を自動的に消すわけではない**

という点です。

論文自身も「modeled inverter voltage」を用いています。([J-STAGE][2])

したがって、あなたなら次をチェックすると非常に面白いです。

* dead-time電圧誤差をどう扱っているか
* Vdc誤差をどう扱っているか
* PWM周期内の実電圧をどこまでモデル化しているか
* oversampling数を増やしたとき、ランダムノイズだけでなくモデル誤差も顕在化しないか
* PLL帯域をどこまで上げられるのか

**「観測量不足」と「モデルバイアス」を区別して読む**と、かなり収穫があるはずです。

---

# 2位：Modulation Signal Optimized Synchronous PWM

### ★★★★★ PWMを「波形生成」ではなく「最適化問題」として読む

これも非常におすすめです。

同期PWMには低次高調波が残り、それが大型径モータの0次モード振動を励起します。本論文は、同期PWMのswitching instantに存在する制約を明示したうえで、**OPP（Optimized Pulse Pattern）的な高調波最適化を通常の同期PWM上で実現する**手法です。専用ハードウェアなしで、問題となる高調波をほぼ除去し、実験ではworst-caseの0次モード振動を約半減しています。([J-STAGE][1])

### あなたとの接続が強い理由

以前のopen-end windingの検討では、

* zero sequence OFF → 6次成分が大きい
* ON → 12次主体
* torque / power / iron-lossへの影響

まで見ています。

その延長線上にこの論文があります。

つまり、

> 「PWMは所定の基本波電圧を出す手段」

から、

> **「基本波を維持したまま、どの高調波をどれだけ作るかを設計する手段」**

へ一段進んだ見方ができます。

### DIY適性も高い

これはかなりDIY向きです。

例えばPython/MATLABで、

`switching angle → Fourier coefficient`

を作り、

`min J = w1·I5² + w2·I7² + ... + λ·THD`

のように最適化するだけでも、論文の思想をかなり再現できます。

**今月のDIY候補を1本選ぶなら、私はこれを推します。**

---

# 3位：A Control-Oriented Approach to Power Balance Compensation in Bidirectional DC-DC Converters

### ★★★★★ 意外にあなた向き

タイトルだけだとDC microgrid論文ですが、これはかなり面白いです。

提案されるPower Balance Control Technique（PBCT）は、

> **input-outputの瞬時電力ミスマッチを明示的に求め、それをインダクタ電流によって補償する**

という構造です。

さらにCPL（Constant Power Load）の**negative incremental impedance**によってDC busが不安定化する問題を扱い、PIやsliding-mode controlとも実験比較しています。EV用高出力DC powertrainでも検証されています。([J-STAGE][1])

これは、あなたが以前検討していた

`ΔP = Pmeas - Pref`

を使う**電力feedback型トルク補償**と思想的にかなり近いです。

もちろん対象Plantは全く違います。しかし、

> 「状態誤差を直接FBするのではなく、物理的なpower balanceの崩れをfeedback量にする」

という設計哲学は共通します。

### 読むポイント

数式を追うなら、

`power mismatch → current correction → plant`

という閉ループをどうモデル化しているかを見てください。

特に、

* power errorをなぜ制御量として選ぶのか
* PI loopとはどう帯域分離しているのか
* CPLによる負性インピーダンスをどう安定化するのか
* SMCに対して何が有利なのか

を読むと、自分の電力feedback方式を整理する材料になりそうです。

---

# 4位：Rapid-Response Load-Side Acceleration Control...

### ★★★★☆ 制御屋として面白い一本

これは**二慣性共振系＋torsion torque＋離散時間sliding mode＋瞬時電圧制御**です。

減速機付きモータを二慣性系として扱い、出力軸の広帯域トルクセンサからtorsion torqueを制御し、さらにPWMより上位の単なるトルク指令ではなく、**inverter instantaneous voltageを直接調整する**ことで高速化しています。simulationと実験の両方があります。([J-STAGE][3])

この論文は、

> 「電流制御器 → トルク → 機械系」

という階層制御をどこまで崩して高速化できるか

という視点で読むと面白いです。

特にe-Axle、shaft resonance、機械共振抑制へ広げるなら価値があります。

---

# 5位：Digital Closed-Loop Dead-Time Minimization...

### ★★★★☆ 「dead-time」という単語だけで飛びつかず読む価値あり

これはモータインバータのdead-time compensationではなく、**PSFBのZVS維持に必要なdead timeをオンラインで最小化する論文**です。

負荷電流だけを使い、非線形MOSFET容量と共振電流をモデル化した離散時間制御により、cycle-by-cycleでdead timeを調整します。追加のZVS検出器は不要。1 kW / 100 kHz実機で、300 W–1 kWの範囲で最大0.2%の効率改善が報告されています。([J-STAGE][4])

あなたの「dead-timeによる電圧モデルバイアス」と**直接同じ問題ではありません**。

しかし、

> dead-timeを固定パラメータとせず、運転状態依存量としてオンライン調整する

という考え方は参考になります。

したがって全文を追うより、

**モデル → 観測量 → dead-time更新則**

の3点だけ拾う読み方で十分です。

---

# 6位：Series-Resonant PMSG System by THD

### ★★★☆☆ モータ屋として軽く読んでおきたい

PMSG＋全波整流器＋直列共振コンデンサという非常にシンプルな発電系です。

今回の論文は、このseries-resonant PMSGを**THDを含めて実験評価**し、高調波が存在しても共振コンデンサ接続により出力を増加できることを示しています。([J-STAGE][1])

制御というより、

**機械＋非線形整流負荷＋共振回路による自然な電力変換**

というシステム設計を見る論文です。

#2のPWM高調波論文と続けて読むと、「高調波＝必ず排除すべきもの」ではないことも含めて対照的で面白いです。

---

# 7位：Gaussian Processによる変圧器故障診断

### ★★★☆☆ ML枠ならこれ

正常変圧器でGaussian Processを学習し、

`measured differential current - GP estimated healthy current`

という**residual**を作り、閾値超過からinter-turn short circuitを検出します。5 kVA実機で検証されています。([J-STAGE][1])

MLモデルそのものより、

> 正常モデルを作る → residualを作る → anomaly detectionする

という構成がきれいです。

モータの故障診断や推定器residual監視にも転用しやすいので、8ページですし読むコストは低いです。

---

## コンバータ論文をもう1テーマ読むなら

**Three-Phase SR-SAB Converter Using Star-Delta Connected Transformer**がよいです。

star-delta transformerでreactive powerを低減し、高周波transformerの小型・低損失化を狙います。さらにtransformer電圧周波数を変えることで、定格の約1/5～定格まで出力範囲を広げ、2.9 kW試作機で検証しています。([J-STAGE][1])

直後の2ページLetterは同じSR-SAB系で、**二次側ダイオード並列の共振Cによりtransformer secondary peak voltageを下げ、耐圧の低いdeviceを使える**という一点を示しています。したがってこの2本はセット読みでよいです。([J-STAGE][1])

以前読んでいた高周波トランス系レビューの延長として読むなら、この組み合わせが今月のconverter枠です。

---

# 私なら9月はこの順番で読みます

**週1本の精読なら**

1. **EEMF Sensorless + Oversampling**
2. **Optimized Synchronous PWM**
3. **Power Balance Compensation**
4. **Discrete-Time Sliding-Mode Torsion-Torque Control**

余力があれば、

**5. Dead-Time Minimization**

までです。

この5本にはちょうど、

`推定 → PWM → power feedback → 機械系制御 → inverter非理想`

という流れがあります。

そのため個別論文をバラバラに読むより、**今月はこの5本を一つの「電動機駆動系をどこまで高帯域・高精度化するか」というテーマとして読む**のがおすすめです。

中でも、**#1 EEMF oversamplingは精読、#2 synchronous PWMはDIY候補**という位置づけにします。([J-STAGE][2])

必要であれば次に、**1位の「Enhanced Extended-EMF-Based PMSM Sensorless Control Using Oversampling」を実際に読み込んで、数式・ブロック図・新規性・あなたのPHF/EKF系との違いまで技術解説**できます。

[1]: https://www.jstage.jst.go.jp/browse/ieejjia/list/-char/en "IEEJ Journal of Industry Applications"
[2]: https://www.jstage.jst.go.jp/article/ieejjia/15/5/15_20250948/_article/-char/en?utm_source=chatgpt.com "Enhanced Extended-EMF-Based PMSM Sensorless Control Using Oversampling"
[3]: https://www.jstage.jst.go.jp/article/ieejjia/15/5/15_20250943/_article/-char/en?utm_source=chatgpt.com "Rapid-Response Load-Side Acceleration Control Based on Discrete-Time Sliding-Mode Torsion-Torque Servoing with Instantaneous Voltage Regulation"
[4]: https://www.jstage.jst.go.jp/article/ieejjia/15/5/15_20251006/_article/-char/en?utm_source=chatgpt.com "Digital Closed-Loop Dead-Time Minimization in Phase-Shifted Full-Bridge Converters without ZVS Detection"
