import { theme as antdTheme, type ThemeConfig } from 'antd';

// ===== 颜色常量 (原 App.tsx 内联硬编码, Task 45 抽取) =====

// 品牌主色 (暗色模式)
const COLOR_PRIMARY = '#3b82f6';
const COLOR_PRIMARY_HOVER = '#2563eb';
const COLOR_PRIMARY_ACTIVE = '#1d4ed8';

// 品牌主色 (亮色模式)
const COLOR_PRIMARY_LIGHT = '#111827';
const COLOR_PRIMARY_HOVER_LIGHT = '#1f2937';
const COLOR_PRIMARY_ACTIVE_LIGHT = '#000000';

// 状态色 (亮暗共用)
const COLOR_SUCCESS = '#10b981';
const COLOR_WARNING = '#f59e0b';
const COLOR_ERROR = '#ef4444';

// 暗色模式 - 背景与表面
const DARK_BG_BASE = '#0f172a';
const DARK_BG_CONTAINER = '#1e293b';
const DARK_BG_LAYOUT = '#0f172a';
const DARK_BG_SPOTLIGHT = '#334155';

// 暗色模式 - 边框
const DARK_BORDER = '#334155';

// 暗色模式 - 文本
const DARK_TEXT = '#f1f5f9';
const DARK_TEXT_SECONDARY = '#94a3b8';
const DARK_TEXT_TERTIARY = '#64748b';
const DARK_TEXT_QUATERNARY = '#475569';

// 暗色模式 - 输入框
const DARK_INPUT_HOVER_BORDER = '#475569';

// 亮色模式 - 背景与表面
const LIGHT_HEADER_BG = '#ffffff';
const LIGHT_SIDER_BG = '#fafafa';
const LIGHT_BODY_BG = '#f7f7f8';

// 亮色模式 - 边框
const LIGHT_BORDER = '#d1d5db';
const LIGHT_BORDER_SECONDARY = '#f0f0f0';

// 亮色模式 - 文本
const LIGHT_TEXT = '#111827';
const LIGHT_TEXT_SECONDARY = '#6b7280';

// 亮色模式 - Menu 悬浮
const LIGHT_ITEM_HOVER_BG = '#f0f0f0';

// ===== 布局常量 =====
const BORDER_RADIUS = 6;
const BORDER_RADIUS_LG = 8;
const FONT_FAMILY =
  '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif';
const FONT_SIZE = 14;
const LINE_HEIGHT = 1.5;

/**
 * 构建 antd ConfigProvider 主题配置。
 * 将原 App.tsx 中 30+ 硬编码颜色抽取为命名常量, 便于统一维护。
 */
export function buildAntdTheme(isDark: boolean): ThemeConfig {
  return {
    algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: isDark ? COLOR_PRIMARY : COLOR_PRIMARY_LIGHT,
      colorInfo: isDark ? COLOR_PRIMARY : COLOR_PRIMARY_LIGHT,
      colorSuccess: COLOR_SUCCESS,
      colorWarning: COLOR_WARNING,
      colorError: COLOR_ERROR,
      borderRadius: BORDER_RADIUS,
      fontFamily: FONT_FAMILY,
      fontSize: FONT_SIZE,
      lineHeight: LINE_HEIGHT,
      ...(isDark
        ? {
            colorBgBase: DARK_BG_BASE,
            colorBgContainer: DARK_BG_CONTAINER,
            colorBgElevated: DARK_BG_CONTAINER,
            colorBgLayout: DARK_BG_LAYOUT,
            colorBgSpotlight: DARK_BG_SPOTLIGHT,
            colorBorder: DARK_BORDER,
            colorBorderSecondary: DARK_BORDER,
            colorText: DARK_TEXT,
            colorTextSecondary: DARK_TEXT_SECONDARY,
            colorTextTertiary: DARK_TEXT_TERTIARY,
            colorTextQuaternary: DARK_TEXT_QUATERNARY,
          }
        : {}),
    },
    components: isDark
      ? {
          Layout: {
            headerBg: DARK_BG_CONTAINER,
            siderBg: DARK_BG_CONTAINER,
            bodyBg: DARK_BG_LAYOUT,
          },
          Menu: {
            itemBg: 'transparent',
            itemSelectedBg: DARK_BG_SPOTLIGHT,
            itemSelectedColor: DARK_TEXT,
            itemHoverBg: DARK_BG_SPOTLIGHT,
            itemHoverColor: DARK_TEXT,
            itemColor: DARK_TEXT_SECONDARY,
            itemBorderRadius: BORDER_RADIUS,
          },
          Button: {
            colorPrimary: COLOR_PRIMARY,
            colorPrimaryHover: COLOR_PRIMARY_HOVER,
            colorPrimaryActive: COLOR_PRIMARY_ACTIVE,
            algorithm: true,
          },
          Input: {
            hoverBorderColor: DARK_INPUT_HOVER_BORDER,
            activeBorderColor: COLOR_PRIMARY,
            borderRadius: BORDER_RADIUS,
          },
          Card: {
            borderRadiusLG: BORDER_RADIUS_LG,
            colorBorderSecondary: DARK_BORDER,
          },
        }
      : {
          Layout: {
            headerBg: LIGHT_HEADER_BG,
            siderBg: LIGHT_SIDER_BG,
            bodyBg: LIGHT_BODY_BG,
          },
          Menu: {
            itemBg: 'transparent',
            itemSelectedBg: LIGHT_HEADER_BG,
            itemSelectedColor: LIGHT_TEXT,
            itemHoverBg: LIGHT_ITEM_HOVER_BG,
            itemHoverColor: LIGHT_TEXT,
            itemColor: LIGHT_TEXT_SECONDARY,
            itemBorderRadius: BORDER_RADIUS,
          },
          Button: {
            colorPrimary: COLOR_PRIMARY_LIGHT,
            colorPrimaryHover: COLOR_PRIMARY_HOVER_LIGHT,
            colorPrimaryActive: COLOR_PRIMARY_ACTIVE_LIGHT,
            algorithm: true,
          },
          Input: {
            hoverBorderColor: LIGHT_BORDER,
            activeBorderColor: LIGHT_TEXT,
            borderRadius: BORDER_RADIUS,
          },
          Card: {
            borderRadiusLG: BORDER_RADIUS_LG,
            colorBorderSecondary: LIGHT_BORDER_SECONDARY,
          },
        },
  };
}
