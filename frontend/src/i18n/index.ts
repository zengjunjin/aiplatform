import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import dayjs from 'dayjs';
import 'dayjs/locale/en';
import 'dayjs/locale/zh-cn';
import zhCN from './zh-CN.json';
import enUS from './en-US.json';

// Task 37: 校验 localStorage 中的语言值是否为项目支持的语言, 不合法回退默认 zh-CN
const SUPPORTED_LANGS = ['zh-CN', 'en-US'] as const;
function getInitialLanguage(): string {
  try {
    const savedLang = localStorage.getItem('i18n-lang');
    if (savedLang && (SUPPORTED_LANGS as readonly string[]).includes(savedLang)) {
      return savedLang;
    }
  } catch {
    // localStorage 不可用时回退默认语言
  }
  return 'zh-CN';
}

i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { translation: zhCN },
    'en-US': { translation: enUS },
  },
  lng: getInitialLanguage(),
  fallbackLng: 'zh-CN',
  interpolation: { escapeValue: false },
});

// 同步 dayjs locale 与 i18n 当前语言，确保相对时间（如 "3 分钟前"）跟随语言切换
dayjs.locale(i18n.language === 'en-US' ? 'en' : 'zh-cn');
i18n.on('languageChanged', (lng) => {
  dayjs.locale(lng === 'en-US' ? 'en' : 'zh-cn');
});

export default i18n;

/**
 * 非 React 组件场景（如 axios 拦截器、store、工具函数）使用的全局 t 函数。
 * 注意: 此函数依赖 i18n 已完成初始化 (main.tsx 中 import './i18n' 保证)。
 */
export const globalT = i18n.t.bind(i18n);