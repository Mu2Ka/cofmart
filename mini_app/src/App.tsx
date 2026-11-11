import { useEffect } from 'react';
import { initializeTelegram } from './lib/telegram';

export default function App() {
  useEffect(initializeTelegram, []);

  return (
    <main className="app">
      <header className="header">
        <a className="brand" href="/" aria-label="Cofmart — главная">cofmart<span>®</span></a>
        <span className="header-note">кофе в твоём ритме</span>
      </header>
      <section className="welcome" aria-labelledby="welcome-title">
        <span className="eyebrow"><span className="dot" /> ТВОЙ ПЕРЕРЫВ НА КОФЕ</span>
        <h1 id="welcome-title">Меньше очередей.<br /><em>Больше кофе.</em></h1>
        <p className="description">Любимый напиток к перерыву —<br />чтобы осталось время на себя.</p>
        <div className="coffee-card" aria-hidden="true">
          <span className="card-label">ХОРОШИЙ ДЕНЬ НАЧИНАЕТСЯ ЗДЕСЬ</span>
          <svg className="cup" viewBox="0 0 240 240" fill="none">
            <path d="M87 48c-13-17 15-22 2-39M119 48c-13-17 15-22 2-39M151 48c-13-17 15-22 2-39" stroke="currentColor" strokeWidth="5" strokeLinecap="round" opacity=".55" />
            <path d="M169 88h13c37 0 37 56 0 56h-14" stroke="currentColor" strokeWidth="9" />
            <path d="M54 76h116v67c0 33-23 55-58 55s-58-22-58-55V76Z" fill="currentColor" />
            <path d="M75 105h72" stroke="#5b704d" strokeWidth="3" opacity=".45" />
            <path d="M44 214h140" stroke="currentColor" strokeWidth="7" strokeLinecap="round" />
          </svg>
          <span className="card-bottom">сделай паузу <span>☕</span></span>
        </div>
        <div className="status">
          <span className="status-icon" aria-hidden="true">↗</span>
          <div><h2>Скоро здесь будет меню</h2><p>Мы готовим кофейни, напитки и предзаказ.<br />Загляни чуть позже!</p></div>
        </div>
      </section>
      <footer>Твой кофе. Твой перерыв.</footer>
    </main>
  );
}
