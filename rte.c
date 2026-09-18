/* 状態の実体を定義する型 */
typedef struct {
    float id_integrator_v;
    float previous_current_u_a;
} UserControlState;

/* ユーザーコードで使う変数名 */
#define f4mv_ctrl_id_int  (state->id_integrator_v)
#define f4mv_pwmg_iu_prev (state->previous_current_u_a)

void user_control_step(
    UserControlState* state,
    float integral_increment_v,
    float current_u_a)
{
    f4mv_ctrl_id_int += integral_increment_v;
    f4mv_pwmg_iu_prev = current_u_a;
}

#undef f4mv_ctrl_id_int
#undef f4mv_pwmg_iu_prev
