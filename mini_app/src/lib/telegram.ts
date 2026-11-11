interface TelegramWebApp {
  initData: string;
  ready(): void;
  expand(): void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export function initializeTelegram(): void {
  const app = window.Telegram?.WebApp;
  if (!app?.initData) return;
  app.ready();
  app.expand();
}
