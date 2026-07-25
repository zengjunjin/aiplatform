/**
 * Task 50: 密码规则统一
 * 抽取共享的密码校验规则, 供注册页 (RegisterPage) 与修改密码弹窗 (Layout) 复用,
 * 避免两处规则不一致 (原 Layout 仅 min 6, 注册页 min 8 + 复杂度)。
 * 统一为: 必填 + 最少 8 字符 + 包含大小写字母/数字/特殊字符。
 */
export const PASSWORD_COMPLEXITY_PATTERN =
  /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>_\-+=[\]\\/]).+$/;

/**
 * 创建密码字段校验规则数组。
 * 因 message 依赖 i18n 的 t 函数, 采用工厂函数在调用时生成。
 * @param t i18n 翻译函数
 * @returns antd Form.Item rules 数组
 */
export function createPasswordRules(t: (key: string) => string) {
  return [
    { required: true, message: t('auth.passwordRequired') },
    { min: 8, message: t('auth.passwordMinLength') },
    {
      pattern: PASSWORD_COMPLEXITY_PATTERN,
      message: t('auth.passwordComplexity'),
    },
  ];
}
