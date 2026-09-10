はい。添付の **“Modulation Signal Optimized Synchronous PWM”** を読むと、この論文はDIY題材としてかなり適しています。しかも、最初からモータ＋振動まで作る必要はありません。**論文の核心はPWM波形生成と最適化だけで独立して再現できる**からです。

## まず、この論文は何をやっているのか

一言で表すと、

> **OPP（Optimized Pulse Pattern）の「高調波を狙って消せる」という利点を、通常の同期PWMで実装できる形に落とした手法**

です。

通常の同期PWMでは、

$$
f_c=N_p f_s
$$

として、キャリア周波数 \(f_c\) を固定子電気周波数 \(f_s\) の整数倍にします。大型機ではスイッチング周波数を上げられないため \(N_p\) が小さくなり、低次の時間高調波が目立ちます。

この論文では特に、

* \(N_p=9\) → 5次・7次を抑制
* \(N_p=15\) → 11次・13次を抑制

します。

これらは \(6n\pm1\) 次高調波であり、大径モータの0次機械モードを励振して騒音・振動を増やす問題につながっています。論文の例では \(N_p=15\) の12次励振成分 \(12f_s\) が機械固有振動数 5645 Hz 付近に来ています。

---

# 論文の核心は「switching angleを直接最適化する」こと

通常のPWMでは、

```text
電圧指令
 ↓
正弦波変調信号
 ↓
三角波キャリアとの比較
 ↓
switching
```

です。

一方OPPでは、最初から

$$
\alpha_1,\alpha_2,\ldots,\alpha_{N_\alpha}
$$

という**switching angleそのものを設計変数**にします。

パルス数との関係は

$$
N_p=2N_\alpha+1
$$

なので、

| \(N_p\) | 最適化するswitching angle数 |
| ------: | --------------------: |
|       9 |                     4 |
|      15 |                     7 |

しかありません。

ここがDIYとしてかなり扱いやすいところです。

---

## OPPでは何を最適化するのか

switching angle \(\alpha_i\) が決まれば、各高調波電圧 \(b_k\) はFourier級数から解析的に計算できます。

そして基本波について、

$$
b_1=\frac{V_{dc}}{2}M
$$

という制約を入れます。

つまり、

> 「要求した基本波電圧 \(M\) は必ず出す」

を守ったまま、高調波を最小化します。

目的関数は論文の式(5)で、

$$
J=
\sum_{j=1}^{8}
\left[
\left(
w_{6j-1}\frac{b_{6j-1}}{6j-1}
\right)^2+
\left(
w_{6j+1}\frac{b_{6j+1}}{6j+1}
\right)^2
\right]
$$

です。

ここで面白いのが

$$
\frac{b_k}{k}
$$

になっている点です。

高調波周波数が \(k\) 倍になるとモータのインダクティブインピーダンスもおおむね \(k\) 倍になるため、**電圧高調波そのものではなく、電流高調波への影響を近似して評価している**わけです。

論文では49次まで評価しています。

さらに対象高調波だけweightを10倍します。

$$
N_p=9:\quad w_5=w_7=10
$$

$$
N_p=15:\quad w_{11}=w_{13}=10
$$

その他は1です。

そしてMATLAB `fmincon` で解いています。

---

# では、普通のOPPと何が違うのか

ここがこの論文の新規性です。

OPPならswitching angleを比較的自由に置けます。

ところが通常の同期PWMでは、あるswitchingは**特定のcarrier区間内でしか発生させられません**。

論文が見つけた制約が式(7)です。

$$
\frac{\pi}{2N_p}(2i-1)
\leq
\alpha_i
\leq
\frac{\pi}{2N_p}(2i+1)
$$

です。

PDF p.3のFig.4を見ると非常に分かりやすいです。各switching angle \(\alpha_i\) は、三角波carrierの対応する山・谷の区間から外へ動けません。

したがってMSOS-PWMは、

$$
\boxed{
\text{OPP最適化}
+
\text{同期PWMで実現可能という制約}
}
$$

になっています。

これがこの論文の本質です。

---

# ここからが非常に巧妙です

switching angleを最適化しただけなら、普通のマイコンPWMへ簡単には入れられません。

そこで論文では、

```text
最適switching angle α
        ↓
対応する変調信号値 m
        ↓
連続した変調波形へ近似
        ↓
普通の同期PWM carrier comparatorへ入力
```

と変換します。

式(8)で、最適化された \(\alpha_i\) を三角波carrierと交差するmodulation値 \(m_i\) に逆変換します。

幾何的には単純です。

三角波はその区間では直線なので、

> 「この時刻 \(\alpha_i\) でcrossさせたいなら、modulation値はいくつにすればよいか」

を逆算しているだけです。

PDF p.3 Fig.5を見ると、その意味がよく分かります。

---

# さらに modulation signal をFourier級数にする

ここが「普通の同期PWMとして実装できる」鍵です。

得られた変調信号を、

$$
m_{ph}(\theta)
=
\sum_{i=1}^{N_\alpha}
M_{2i-1}\sin[(2i-1)\theta]
$$

で近似します。

したがって \(N_p=9\) なら、

$$
m_{ph}
=
M_1\sin\theta
+M_3\sin3\theta
+M_5\sin5\theta
+M_7\sin7\theta
$$

です。

\(N_p=15\) なら、

$$
1,3,5,7,9,11,13
$$

次まで使います。

つまり実機ではswitching angleテーブルを直接再生するのではなく、

> **少数の正弦波を足し合わせたmodulation signal**

として扱えます。

ここがOPPより実装しやすい理由です。

---

# OfflineとOnlineを分けて考えると非常に分かりやすい

この方式は実質的に二段構成です。

### Offline

ある \(N_p\) と変調率 \(M\) に対して、

$$
M
\rightarrow
\alpha_1,\ldots,\alpha_{N_\alpha}
$$

を最適化します。

そこから

$$
\alpha_i\rightarrow m_i
$$

へ変換し、

$$
m_i\rightarrow
M_1,M_3,M_5,\ldots
$$

というFourier係数にします。

そして変調率を掃引して、

$$
M_1(M),M_3(M),M_5(M),\ldots
$$

というLUTを作ります。

### Online

実機ではもう最適化しません。

現在の電圧指令から \(M\) を求め、

```text
M
 ↓
LUT
 ↓
M1, M3, M5 ...
 ↓
sin θ, sin 3θ, sin 5θ ...
 ↓
通常のPWM指令へ加算
```

するだけです。

したがってランタイム負荷はかなり小さい構造です。

---

# Fig.11はDIYするなら非常に重要

PDF p.5のFig.11が実装ブロック図です。

通常のFOCから

$$
v_{dq}^*
$$

が出ます。

これを普通にdq→uvw変換し、

$$
m'_u,m'_v,m'_w
$$

という従来PWM指令を作ります。

それとは別branchで \(v_{dq}^*\) をLPFに通し、振幅とphaseを取得します。LPF cutoffは**current control responseの1/5**です。

振幅についてFig.11は、

$$
M=
\frac{\sqrt{2/3}\,|v_{dq}^*|}
{V_{dc}/2}
$$

という構成になっています。

この \(\sqrt{2/3}\) は重要です。電力不変dqのベクトル振幅をphase peakへ換算する構成と整合しているため、あなたがベース制御で使っている電力不変dqとはかなり接続しやすいです。

---

## Fig.11をさらによく見ると面白い

基本波については、単に \(M_1\sin\theta\) を通常PWMへ追加しているわけではありません。

通常PWM側にすでに

$$
M\sin\theta
$$

が存在するからです。

したがって補正側では実質、

$$
(M_1(M)-M)\sin\theta
$$

を作っています。

そして、

$$
M_3(M)\sin3\theta+
M_5(M)\sin5\theta+\cdots
$$

を加える。

つまりオンライン実装のイメージは、

$$
\boxed{
m=
m_{\rm conventional}
+
\Delta m_{\rm MSOS}
}
$$

です。

**既存FOC/PWMを捨てる方式ではなく、既存の電圧指令にmodulation補正をかぶせる方式**です。

これはDIYするうえで非常に大きな利点です。

---

# 結果も少し意外です

理想simulationではMSOS-PWMによって対象高調波はほぼ消えています。

PDF p.4 Fig.8, Fig.9を見ると、

* \(N_p=15\)：11次・13次
* \(N_p=9\)：5次・7次

がOPPに近いレベルまで落ちています。

ただし**高調波を消す＝総合歪みが必ず下がる、ではありません。**

Fig.10では、

* \(N_p=9\)：MSOSはWTHDをかなり改善し、OPP並み
* \(N_p=15\)：MSOSのWTHDは通常同期PWMとほぼ同じで、OPPほど良くない

となっています。

つまり、

> 5次・7次、あるいは11次・13次を消すために、別の高調波へエネルギーを逃がしている

面があります。

これはDIYでかなり面白い観察ポイントです。

---

# 実機結果を見るとさらに面白い

実験機は9 pole pairs、最大30 Nm、100 Arms、Vdc=100 Vです。current controller crossoverは333 rad/s、dead timeは5 µsです。

しかも**dead-time compensationなし**です。

### \(N_p=15\)

通常同期PWMではFig.13より、

* \(WTHD_0=2.39\%\)
* current THD = 11.4%

MSOS-PWMではFig.14より、

* \(WTHD_0=2.55\%\)
* current THD = 12.0%

です。

つまり**対象11/13次は激減しているのに、総合歪みは少し悪化**しています。

これは非常に重要な結果です。

### \(N_p=9\)

通常同期PWMでは、

* \(WTHD_0=4.08\%\)
* current THD = 24.7%

MSOSでは、

* \(WTHD_0=3.64\%\)
* current THD = 19.9%

まで下がっています。

こちらは対象高調波除去と総合歪み改善が両立しています。

---

# 私がこの論文で最も面白いと思うのはdead timeです

PDF p.6 Fig.17です。

論文ではideal条件と、

* semiconductor voltage drop
* dead time
* 両方

を入れたJMAG-RT simulationを比較しています。

その結果、

**通常同期PWMは電圧誤差に比較的robust。**

一方でMSOS-PWMは、

* \(N_p=15\)：dead timeでWTHDがかなり悪化
* \(N_p=9\)：悪化がかなり小さい

となっています。

これはDIYテーマとして非常に良いです。

単に

> 「論文どおり高調波が消えました」

で終わらず、

$$
V_{\rm ideal}
\rightarrow
V_{\rm inverter}
=
V^*+\Delta V_{\rm deadtime}+\Delta V_{\rm device}
$$

としたとき、

> **最適化PWMはモデル誤差にどこまでrobustなのか？**

という一段深い問いに進めます。

これまであなたが扱ってきたインバータ非理想や電圧誤差の問題ともかなり接続しやすい部分です。

---

# 動特性を犠牲にしていないのもポイント

論文ではtorque referenceを

$$
5\ {\rm Nm}\rightarrow15\ {\rm Nm}
$$

へstepさせています。

設計したcurrent responseの時定数は3 msです。

MSOSでもほぼ同じ応答になっています。

ただし \(N_p=15\) では通常同期PWMよりわずかに遅くなります。

論文の説明は明確で、

> MSOS用のharmonic modulationを追加したことで、feedback controllerが利用できる電圧marginが少し減った

ためです。

これも重要です。

MSOSはcurrent controllerを置き換えていません。

```text
current control
    ↓
基本電圧指令
    ↓
MSOS modulation補正
    ↓
PWM
```

なので、既存FOCへ後付けしやすい方式です。

---

# 最終的な振動効果

18個のaccelerometerをモータ円周上へ配置し、同相成分から0次mode vibrationを抽出しています。

対象高調波を除去した結果、**0次mode vibrationのworst caseを約1/2に低減**しています。

ただしDIYでここまで再現しようとすると、

* motor spatial harmonics
* radial electromagnetic force
* mechanical modal characteristics

まで必要になります。

したがって私は、ここは最初のDIY対象にはしません。

---

# この論文をDIYするなら、どこまで作れば「再現」と言えるか

最初のDIYとして最も適切なのは、**モータモデルなしでFig.6～Fig.10までを再現すること**だと思います。

中心となる問いは次の3つです。

| 問い                                    | 得たい答え                                      |
| ------------------------------------- | ------------------------------------------ |
| **Q1** MSOS制約下でも対象高調波を除去できるか          | \(b_5,b_7\) または \(b_{11},b_{13}\) vs \(M\) |
| **Q2** 対象高調波除去と総合歪みにはどんなtrade-offがあるか | WTHD vs \(M\)、Sync/OPP/MSOS比較              |
| **Q3** inverter非理想を入れたとき性能はどう崩れるか     | dead time / device drop感度                  |

この3問だけでも、一つのかなり完成度の高いDIYになります。

その後、

$$
\text{PWM-only}
\rightarrow
\text{PMSM + current control}
\rightarrow
\text{dead-time}
\rightarrow
\text{JMAG-RT}
$$

と拡張できます。

---

## 実装前に知っておくべき「論文だけでは確定しない部分」

ここは重要です。

論文には、**\(M_1(M),M_3(M),\dots\) を具体的にどう同定したかが十分詳しく書かれていません。** 式(9)の関数形とLUTを使うことは書かれていますが、係数算出の具体的な数値アルゴリズムやLUTの \(M\) 刻みは明記されていません。

またFig.11の \(\theta_{s,\sin}\) 算出部分には、角度加算器へ **\(v_{dc}/2\)** と読める表記があります。これは次元的に不整合なので、そのまま実装すべきではありません。位相offset等の図中誤記の可能性がありますが、添付論文だけからは確定できません。

この2点は、実装前に解消しておいた方がよいです。

---

## DIY候補としての評価

私は前回よりさらに評価を上げます。

**DIY適性は非常に高いです。**

理由は、最適化問題が小さく、論文中に比較baselineが3つあり、

$$
\text{Synchronous PWM}
\quad vs\quad
\text{OPP}
\quad vs\quad
\text{MSOS-PWM}
$$

を同じ指標で比較できるからです。

さらに「成功した」だけでなく、

> **なぜ \(N_p=9\) では総合歪みまで改善するのに、\(N_p=15\) では対象高調波を消してもWTHDが改善しないのか？**

> **なぜdead timeへの感度が \(N_p=9\) と15でこれほど違うのか？**

という、論文を再現した後に自分で掘れる問いがあります。

ここまで含めると、単なる論文追試ではなく、**技術報告書にできるDIYテーマ**になります。

次に着手するなら、コードを書く前にこの論文について **「何を再現し、どこから自分の追加検証にするか」まで含めたDIY企画書**を固めるのがよい段階です。
