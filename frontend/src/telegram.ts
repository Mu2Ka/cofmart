type TelegramWebApp = {
  initData: string;
  ready: () => void;
  expand: () => void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export const telegram = window.Telegram?.WebApp;
export const initData = telegram?.initData ?? "";

telegram?.ready();
telegram?.expand();
