# Q–P二段Δ推定の追加文献調査

調査日：2026-09-13。対象：[QP_estimater.md](QP_estimater.md)。国外の原著を中心に、既に選定した8本と重複しない資料を調査した。

## 調査結果

**優先文献8本、構想に近い補助資料2件を選定した。** 特にJung–Oh（2023）は、IPMSMの無効エネルギーから磁石温度を求め、その結果を有効エネルギー側に使って巻線温度を求める。Wangほか（2026）は、Q相当量による磁気パラメータ同定とPによる抵抗同定を本文で説明している。「無効側で磁気状態を求め、有効側へ戻す」という構造には、直接比較すべき先行研究がある。[Jung–Ohの公式要旨](https://pure.dongguk.edu/en/publications/estimation-of-stator-and-magnet-temperatures-of-ipmsm-from-active/)、[Wangほかの本文](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/elp2.70185)

今回の構想との比較点は、**非線形IPMSMのTyp＋低速Δを、トルク実測や専用注入に依存せず推定し、その結果でP残差から等価インバータ電圧誤差を求める場合の成立条件**である。今回確認した範囲で、この組合せ全体と同一の実証までは確認できていない。これは新規性の判定ではなく、文献比較で残った確認事項である。

以下では「本文確認」「公式要旨確認」「プレプリント」を区別する。本文未確認の論文について、要旨から推定アルゴリズムの細部まで補わない。リンクは出版社、大学、著者公開稿を優先した。

## 優先して読む8本

### 1. Jung & Oh, 2023 — IPMSMの無効側→有効側の二段推定

**Hyun-Sam Jung, Do-Young Oh. “Estimation of Stator and Magnet Temperatures of IPMSM From Active and Reactive Energies at Medium and High Speeds.”** IEEE Transactions on Transportation Electrification, 9(2), 2983–2993, 2023. DOI: [10.1109/TTE.2022.3220263](https://doi.org/10.1109/TTE.2022.3220263)

- **選定理由：今回の二段構造に最も近いIPMSM文献。** 無効エネルギーから巻線抵抗情報なしで磁石温度を推定し、その推定値を使った有効エネルギーから巻線温度を推定する。温度によるインダクタンス変化と速度依存性も考慮する。
- **確認範囲：大学公式要旨。本文未確認。** 当該オンライン検証では磁石温度の最大誤差5°C未満、巻線温度10°C未満と報告している。
- **本文で確認したい点：** reactive/active energyの定義と本メモのQ/Pとの対応、温度校正マップ、電圧の取得方法、注入・励振条件、インバータ非線形の処理。等価デッドタイムの独立推定まで行うとは確認できていない。

出典：[大学公式の書誌・要旨](https://pure.dongguk.edu/en/publications/estimation-of-stator-and-magnet-temperatures-of-ipmsm-from-active/)、[IEEE原論文](https://ieeexplore.ieee.org/document/9940992)

### 2. Jung et al., 2021 — インダクタンス変化を含むQ系の磁気状態推定

**Hyun-Sam Jung, Hwigon Kim, Seung-Ki Sul, Daniel J. Berry. “Temperature Estimation of IPMSM by Using Fundamental Reactive Energy Considering Variation of Inductances.”** IEEE Transactions on Power Electronics, 36(5), 5771–5783, 2021. DOI: [10.1109/TPEL.2020.3028084](https://doi.org/10.1109/TPEL.2020.3028084)

- **選定理由：Q側の設計に直接役立つ。** 中高速IPMSMで、磁石磁束だけでなく温度に伴うインダクタンス変化を無効エネルギーに反映し、磁石温度を推定する。
- **確認範囲：大学・IEEEの公式要旨。本文未確認。** 巻線抵抗誤差の影響を除去し、インバータ非線形とAC抵抗に対して頑健とする。速度・トルクが変化する10,000秒の試験で温度誤差3.7°C未満と報告。
- **本文で確認したい点：** 基本波の抽出、平均化の順序、非線形誤差が消える仮定、温度と磁気パラメータの関係。本論文の温度推定を、そのまま独立したΔLd・ΔLq・Δφの三変数同定と解釈しない。

出典：[大学公式の書誌・要旨](https://pure.dongguk.edu/en/publications/temperature-estimation-of-ipmsm-by-using-fundamental-reactive-ene/)、[IEEE原論文](https://ieeexplore.ieee.org/document/9210534/)

### 3. Wang et al., 2026 — Q/P分離と識別条件を本文で追える近接例

**Peng Wang, Z. Q. Zhu, Zhibin Feng. “Online Parameter Identification of SPMSMs Under Sensorless Control Cancelling Influence of Position Error With Torque Measurements.”** IET Electric Power Applications, 20(1), e70185, 2026. DOI: [10.1049/elp2.70185](https://doi.org/10.1049/elp2.70185)

- **選定理由：Q/Pによる分離を数式で比較できる。** §4.1.1、式(17)–(23)でQ相当量から抵抗項と平均モデルのVSI非線形項を除去する。§4.1.2では有効電力側から抵抗を同定する。
- **確認範囲：出版社OA本文。** 600 Wの表面磁石型同期発電機による実験。
- **重要な違い：** トルク実測と正負5°の位置オフセット注入を使う。式(27)の説明に残るrank不足を、複数状態によって解く。トルク測定だけで無条件に識別可能とは読まない。P側の抵抗同定前に、別手法でVSI補償を行う。
- **読む箇所：** §4.1–4.3。§4.3.2はIPMSMや強い飽和突極性への直接適用を否定している。

出典：[出版社OA全文](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/elp2.70185)

### 4. Feng et al., 2016 — Pを使った抵抗・VSI非線形の分離

**Guodong Feng, Chunyan Lai, Kaushik Mukherjee, Narayan C. Kar. “Current Injection-Based Online Parameter and VSI Nonlinearity Estimation for PMSM Drives Using Current and Voltage DC Components.”** IEEE Transactions on Transportation Electrification, 2(2), 119–128, 2016. DOI: [10.1109/TTE.2016.2538180](https://doi.org/10.1109/TTE.2016.2538180)

- **選定理由：今回のP側モデルと実験条件を作る参考。** 有効電力式と一定トルク条件を用い、2回のd軸電流注入による計3定常点から抵抗・VSI非線形を先に推定し、その後に磁気パラメータを求める。
- **確認範囲：著者公開本文。** 4.25 kW IPMSMで実験。推定順序は今回のQ→Pと異なる。
- **重要な限界：** 小注入中のVSI誤差一定などを仮定する。またp.121ではインバータの等価抵抗をモータ抵抗に含める。I²とIの違いを使っても、巻線抵抗と素子の抵抗性電圧降下が物理的に分かれるとは限らない。
- **読む箇所：** §II、§IIIの式(7)–(16)、§V。

出典：[著者公開PDF](https://www.researchgate.net/profile/Guodong-Feng-3/publication/304580955_05257181/links/57741a1508ae1b18a7de402c/05257181.pdf)

### 5. Chen et al., 2022 — 等価デッドタイムモデルと同定値の意味

**Jiahao Chen, Jie Mei, Xin Yuan, Yuefei Zuo, Jingwei Zhu, Christopher H. T. Lee. “Online Adaptation of Two-Parameter Inverter Model in Sensorless Motor Drives.”** IEEE Transactions on Industrial Electronics, 69(10), 9860–9871, 2022. DOI: [10.1109/TIE.2021.3139173](https://doi.org/10.1109/TIE.2021.3139173)

- **選定理由：等価Dtを一つの定数にするか、電流依存形状も扱うかを判断できる。** 電流に対するsigmoid形のインバータ誤差を、振幅とゼロクロス付近の形状の二変数で適応する。
- **確認範囲：著者プレプリント本文、大学公式書誌。** 750 W SPMSMを2台使用し、IGBT・SiCインバータで検証。事前同定したactive fluxを必要とする。
- **重要な限界：** §V-Eでは抵抗設定を50%・200%に変えると、推定した誤差振幅が抵抗誤差を吸収する。低電流域では二変数が干渉し、物理値への収束を保証しない。補償性能と物理パラメータの同定を分けて評価する根拠になる。
- **読む箇所：** §II、§IV、§V-E、§VII。

出典：[大学公式書誌](https://abdn.elsevierpure.com/en/publications/online-adaptation-of-two-parameter-inverter-model-in-sensorless-m/)、[公開プレプリントDOI](https://doi.org/10.36227/techrxiv.17309948.v1)、[確認した著者公開稿](https://www.researchgate.net/publication/357283099_Online_Adaptation_of_Two-Parameter_Inverter_Model_in_Sensorless_Motor_Drives)

### 6. Specht et al., 2014 — 非線形Typマップ＋ゆっくりした磁束補正

**Andreas Specht, Oliver Wallscheid, Joachim Böcker. “Determination of Rotor Temperature for an Interior Permanent Magnet Synchronous Machine Using a Precise Flux Observer.”** IPEC-Hiroshima, 1501–1507, 2014. DOI: [10.1109/IPEC.2014.6869784](https://doi.org/10.1109/IPEC.2014.6869784)

- **選定理由：Typ＋低速Δを具体的に実装する参考。** 基準温度の非線形磁束–電流LUTにd軸磁束補正を加え、電流予測残差の積分から磁束変化・温度を求める。飽和と速度依存鉄損もモデルに含める。
- **確認範囲：著者公開本文。** IPMSM実機で検証し、追加高周波注入を必要としない。
- **重要な違い：** Q射影ではないため、抵抗の温度補正や端子電圧精度が必要。温度変化をd軸磁束のシフトで表す仮定の適用範囲も確認する。
- **読む箇所：** §II–VI、特に式(7)、(12)–(14)。

出典：[著者公開本文](https://www.researchgate.net/publication/262726438_Determination_of_Rotor_Temperature_for_an_Interior_Permanent_Magnet_Synchronous_Machine_Using_a_Precise_Flux_Observer)

### 7. Piippo et al., 2009 — 運転領域ごとに推定対象を選ぶ

**Antti Piippo, Marko Hinkkanen, Jorma Luomi. “Adaptation of Motor Parameters in Sensorless PMSM Drives.”** IEEE Transactions on Industry Applications, 45(1), 203–212, 2009. DOI: [10.1109/TIA.2008.2009614](https://doi.org/10.1109/TIA.2008.2009614)

- **選定理由：自然運転中のΔ更新を、情報が得られる領域に限定する考え方。** 低速では高周波注入から得る情報で抵抗を、中高速では磁石磁束を適応する。定常基本波情報による未知数の識別制約を議論する。
- **確認範囲：大学公開の著者最終稿。** 2.2 kW埋込磁石機で実験。
- **重要な違い：** 低速で高周波注入を使う。実験機の飽和は比較的小さく、強飽和IPMSMの全磁気パラメータ同時推定の根拠にはならない。
- **読む箇所：** §IV-A、IV-C–E、V。

出典：[大学公開PDF](https://acris.aalto.fi/ws/portalfiles/portal/4504376/j13_post.pdf)、[大学書誌](https://aaltodoc.aalto.fi/items/94513e58-0dd2-4180-9142-aa797d23e731)

### 8. Perera & Nilsen, 2022 — 遅い適応と感度に応じたゲイン設定

**Aravinda Perera, Roy Nilsen. “Recursive Prediction Error Gradient-Based Algorithms and Framework to Identify PMSM Parameters Online.”** arXiv:2209.05094, 2022. DOI: [10.48550/arXiv.2209.05094](https://doi.org/10.48550/arXiv.2209.05094)

- **選定理由：Typを与えたうえで温度由来の遅い変化を追う実装に合う。** インダクタンスをオフラインで与え、磁石磁束と抵抗をオンライン適応する。数秒程度の適応時定数や感度に基づく速度別ゲインを議論する。
- **確認範囲：著者公開プレプリント本文。査読誌版は未確認。** 3 kW IPMSM実機を含む。
- **重要な違い：** Q射影を使わず、VSIは事前デッドタイム補償する。初期モデルの精度と、各速度域におけるパラメータ感度を前提とする。
- **読む箇所：** §III-E、IV、VI。

出典：[著者公開全文](https://arxiv.org/html/2209.05094v1)、[PDF](https://arxiv.org/pdf/2209.05094)

## 論文以外でも残す価値が高い2件

### S1. Welchko et al. — Torque estimator for IPM motors

**Brian A. Welchko, Silva Hiti, Steven E. Schulz. “Torque estimator for IPM motors.”** 米国特許US7774148B2。出願2007年、公開公報US20080183405A1は2008年、B2公報は2010年。

**Qと既知のq軸磁束マップからd軸磁束を求め、トルクへ変換する**構成が記載されている。式(12)の一式二未知数に対し、式(13)で事前特性化したq軸磁束を与え、式(14)–(15)でd軸磁束・トルクを算出する。今回の「Lq側を既知として必要な磁気量を求める」代案との比較に有用。

本文確認済み。低速・d軸電流が小さい領域で信頼性が落ちることを明記する。誤差除去の説明は抵抗型損失モデルに基づくため、任意の鉄損や任意のインバータ誤差が消えるとの一般化は避ける。実機性能の検証資料としてではなく、構成・数式の先行例として使う。

出典：[公報全文](https://patents.google.com/patent/US7774148B2/en)

### S2. Montalba Mesa, 2021 — Q残差＋基準磁束マップの実装例

**Raimundo Esteban Montalba Mesa. “Online Parameter Estimation of a Six-Phase Machine for Marine Application.”** KTH修士論文、2021。

§5、式(5.18)と§7.2では、**基準の非線形磁束マップが与えるQと測定電圧・電流によるQとの差を、基準磁石磁束への補正量にする**。Typ＋ΔをQ残差から求める具体例として近い。

関連章の本文確認済み。ただし対象は六相機で、磁気インダクタンスの変化を無視して差分を磁石磁束へ帰属する。§7.2.2の検証モデルは熱モデルを持たず、磁束マップに人工的な変化を与えるシミュレーションである。実温度変化下でΔLd・ΔLq・Δφを同時に分離した証拠ではない。

出典：[大学リポジトリの全文PDF](https://www.diva-portal.org/smash/get/diva2:1594920/FULLTEXT01.pdf)

## 本文を追加取得する候補

**Chuanqiang Lian, Fei Xiao, Jilong Liu, Shan Gao. “Parameter and VSI Nonlinearity Hybrid Estimation for PMSM Drives Based on Recursive Least Square.”** IEEE Transactions on Transportation Electrification, 9(2), 2195–2206, 2023. DOI: [10.1109/TTE.2022.3206606](https://doi.org/10.1109/TTE.2022.3206606)

書誌は出版社登録情報・共著者ORCIDで確認した。今回、出版社本文と一次公開された要旨は確認できなかったため、技術内容の確定した根拠には採用していない。取得後に、基準テーブルとオンライン補正の構成、磁気パラメータとVSI誤差の分離条件を確認したい。

入手・書誌確認先：[IEEE](https://ieeexplore.ieee.org/document/9889693/)、[共著者Fei XiaoのORCID](https://orcid.org/0000-0001-5584-6626)

## この構想に戻して確認する3点

以下は文献を踏まえた本調査の整理・数式上の推論であり、個々の論文の結論をそのまま転記したものではない。

1. **Qの残差から何を推定するか。** メモの線形化モデルでは回帰ベクトルは ωe[id², iq², id]。同じ電流動作点では速度だけ変えても方向は増えず、ΔLd・ΔLq・Δφの三変数分離にはならない。id=0ではLdとφはQに現れない。Typや正則化は有用な事前情報だが、測定情報が増えたこととは区別する。温度1変数、磁束補正1変数、複数磁気Δのどれを使うかは、実際に得られる運転点で決める。
2. **P残差の帰属先。** 電流に平行な電圧誤差はQから消える一方、Pに残る。巻線抵抗誤差、素子の抵抗性電圧降下、一定振幅型のVSI誤差などを、どの程度まとめて等価誤差とするかを定義する。Feng（2016）とChen（2022）は、この区別に具体的な材料を与える。
3. **平均化と適用領域。** Qに対して抵抗が消えることと、一般の過渡磁束項・高調波・測定誤差が消えることは別である。基本波抽出、積を取る前後の平均化、低速・小id、加減速中の扱いを揃えて先行法と比較する。

読む順序は、構想の位置づけに **1→2→3**、P側のモデルに **4→5**、実装時のマップ・更新速度・更新領域に **6→7→8**。S1・S2は、推定変数を減らす案を検討するときに併読する。
