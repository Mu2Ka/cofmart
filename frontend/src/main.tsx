import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ApiError,
  request,
  type Cafe,
  type ItemInput,
  type MenuItem,
  type Order,
  type OrderRequest,
  type Preview,
  type Slot,
} from "./api";
import { initData } from "./telegram";
import "./style.css";

const money = (value: number) =>
  new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 2,
  }).format(value / 100);
const time = (value: string, zone: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    timeZone: zone,
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
// Used only to namespace local retry state, never to authorize a request.
function retryStorageKey() {
  try {
    return `cofmart:pending:${JSON.parse(new URLSearchParams(initData).get("user") ?? "{}").id ?? "anonymous"}`;
  } catch {
    return "cofmart:pending:anonymous";
  }
}
const storageKey = retryStorageKey();
function readPending(): OrderRequest | null {
  try {
    return JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
  } catch {
    return null;
  }
}

function App() {
  const [pending, setPendingState] = useState<OrderRequest | null>(readPending);
  const [cafes, setCafes] = useState<Cafe[]>([]);
  const [cafeId, setCafeId] = useState<number | null>(pending?.cafe_id ?? null);
  const [menu, setMenu] = useState<MenuItem[]>([]);
  const [cart, setCart] = useState<Record<number, number>>(() =>
    Object.fromEntries(
      (pending?.items ?? []).map((x) => [x.menu_item_id, x.quantity]),
    ),
  );
  const [preview, setPreview] = useState<Preview | null>(null);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [slotId, setSlotId] = useState<number | null>(pending?.slot_id ?? null);
  const [view, setView] = useState<"menu" | "review" | "history">(
    pending ? "review" : "menu",
  );
  const [history, setHistory] = useState<Order[]>([]);
  const [success, setSuccess] = useState<Order | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const cafe = cafes.find((x) => x.id === cafeId);
  const count = Object.values(cart).reduce((a, b) => a + b, 0);
  const items = (): ItemInput[] =>
    Object.entries(cart)
      .filter(([, q]) => q > 0)
      .map(([id, quantity]) => ({ menu_item_id: Number(id), quantity }));

  function setPending(value: OrderRequest | null) {
    setPendingState(value);
    try {
      if (value) sessionStorage.setItem(storageKey, JSON.stringify(value));
      else sessionStorage.removeItem(storageKey);
    } catch {
      /* memory retry still works */
    }
  }
  function report(exc: unknown) {
    setError(
      exc instanceof Error ? exc.message : "Не удалось загрузить данные.",
    );
  }

  useEffect(() => {
    if (!initData) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    request<Cafe[]>("/cafes", undefined, controller.signal)
      .then((data) => {
        setCafes(data);
        setCafeId((current) => current ?? data[0]?.id ?? null);
      })
      .catch((e) => {
        if (!controller.signal.aborted) report(e);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!cafeId || !initData) return;
    const controller = new AbortController();
    setMenu([]);
    request<MenuItem[]>(`/cafes/${cafeId}/menu`, undefined, controller.signal)
      .then(setMenu)
      .catch((e) => {
        if (!controller.signal.aborted) report(e);
      });
    return () => controller.abort();
  }, [cafeId]);

  async function review() {
    setBusy(true);
    setError("");
    try {
      const [calculation, times] = await Promise.all([
        request<Preview>("/orders/preview", {
          cafe_id: cafeId,
          items: items(),
        }),
        request<Slot[]>(`/cafes/${cafeId}/slots`),
      ]);
      setPreview(calculation);
      setSlots(times);
      setSlotId(null);
      setView("review");
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (submitting.current || (!pending && (!preview || !slotId || !cafeId)))
      return;
    const command: OrderRequest = pending ?? {
      cafe_id: cafeId!,
      slot_id: slotId!,
      items: items(),
      expected_total_minor: preview!.total_minor,
      idempotency_key: crypto.randomUUID(),
    };
    submitting.current = true;
    setPending(command);
    setBusy(true);
    setError("");
    try {
      const order = await request<Order>("/orders", command);
      setSuccess(order);
      setPending(null);
      setCart({});
      setPreview(null);
      setView("menu");
    } catch (e) {
      report(e);
      // A network/server failure has an unknown outcome: retry the exact same key.
      if (e instanceof ApiError && e.status < 500 && e.status !== 401) {
        setPending(null);
        if (e.code === "PRICE_CHANGED" || e.code === "SLOT_UNAVAILABLE") {
          await review();
          setError(e.message);
        }
      }
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  async function showHistory() {
    setBusy(true);
    setError("");
    try {
      setHistory(await request<Order[]>("/orders"));
      setView("history");
      setSuccess(null);
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }

  function changeQuantity(id: number, delta: number) {
    if (busy || pending) return;
    setCart((current) => {
      const next = {
        ...current,
        [id]: Math.max(0, (current[id] ?? 0) + delta),
      };
      if (next[id] === 0) delete next[id];
      return next;
    });
    setPreview(null);
    setSuccess(null);
  }

  if (!initData)
    return (
      <main className="welcome">
        <span className="mark">c.</span>
        <h1>
          Ваш кофе.
          <br />В ваше время.
        </h1>
        <p>
          Откройте Cofmart через кнопку Mini App в Telegram-боте, чтобы выбрать
          кофейню и оформить заказ.
        </p>
        <span className="tag">Заказы также доступны через кнопки бота</span>
      </main>
    );

  return (
    <main>
      <header>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            if (!busy && !pending) setView("menu");
          }}
        >
          cofmart<span>●</span>
        </a>
        <button
          className="quiet"
          disabled={busy || !!pending}
          onClick={showHistory}
        >
          Мои заказы ↗
        </button>
      </header>
      <section className="intro">
        <span className="eyebrow">МАЛЕНЬКАЯ ПАУЗА. ХОРОШИЙ КОФЕ.</span>
        <h1>
          Кофе будет.
          <br />
          <em>Когда вам удобно.</em>
        </h1>
        <p>Выберите любимый напиток, а мы сохраним время для вас.</p>
      </section>
      {error && (
        <div className="notice" role="alert">
          {error}
          <button
            className="quiet"
            onClick={() => window.location.reload()}
            disabled={busy}
          >
            Обновить
          </button>
        </div>
      )}
      {loading && <p role="status">Загружаем кофейни…</p>}
      {success && (
        <section className="success" role="status">
          <span className="eyebrow">ВСТРЕТИМСЯ ЗА КОФЕ</span>
          <h2>Заказ №{success.id} подтверждён ✓</h2>
          <p>
            {success.cafe_name} · {time(success.starts_at, success.timezone)}
          </p>
          <OrderLines order={success} />
          <button onClick={() => setSuccess(null)}>Выбрать ещё</button>
        </section>
      )}
      {view === "history" ? (
        <section>
          <div className="section-title">
            <h2>Ваши заказы</h2>
            <button className="quiet" onClick={() => setView("menu")}>
              ← В меню
            </button>
          </div>
          {!history.length && <p>Здесь появится ваш первый заказ.</p>}
          {history.map((order) => (
            <article className="order" key={order.id}>
              <span className="eyebrow">ЗАКАЗ №{order.id} · ПОДТВЕРЖДЁН</span>
              <h3>{order.cafe_name}</h3>
              <p>{time(order.starts_at, order.timezone)}</p>
              <OrderLines order={order} />
            </article>
          ))}
        </section>
      ) : (
        <>
          <div className="section-title">
            <h2>{view === "review" ? "Почти готово" : "Загляните за кофе"}</h2>
            <span className="tag">С собой, без спешки</span>
          </div>
          {view === "menu" && (
            <>
              <div className="cafes" aria-label="Кофейни">
                {cafes.map((x) => (
                  <button
                    key={x.id}
                    className={x.id === cafeId ? "cafe selected" : "cafe"}
                    disabled={busy || !!pending}
                    onClick={() => {
                      if (x.id !== cafeId) {
                        setCafeId(x.id);
                        setCart({});
                        setPreview(null);
                        setSuccess(null);
                        setError("");
                      }
                    }}
                  >
                    <span>КОФЕЙНЯ</span>
                    <strong>{x.name}</strong>
                    <span>
                      {x.id === cafeId ? "Выбрана ↗" : "Посмотреть меню ↗"}
                    </span>
                  </button>
                ))}
              </div>
              {!loading && cafes.length === 0 && <p>Кофейни скоро появятся.</p>}
              {cafe && (
                <div className="section-title">
                  <h2>Меню · {cafe.name}</h2>
                  <span>{menu.length} напитка</span>
                </div>
              )}
              <div className="menu">
                {menu.map((x, index) => (
                  <article className="drink" key={x.id}>
                    <div
                      className={`cup-scene shade-${index % 4}`}
                      aria-hidden="true"
                    >
                      <div className="cup">
                        <span>c.</span>
                      </div>
                      <span className="cup-caption">СВАРЕНО ДЛЯ ВАС</span>
                    </div>
                    <div className="drink-info">
                      <h3>{x.name}</h3>
                      <div className="drink-bottom">
                        <span>{money(x.price_minor)}</span>
                        <div className="quantity">
                          {cart[x.id] ? (
                            <>
                              <button
                                aria-label={`Убрать ${x.name}`}
                                onClick={() => changeQuantity(x.id, -1)}
                              >
                                −
                              </button>
                              <output>{cart[x.id]}</output>
                            </>
                          ) : null}
                          <button
                            aria-label={`Добавить ${x.name}`}
                            onClick={() => changeQuantity(x.id, 1)}
                            disabled={busy || !!pending}
                          >
                            +
                          </button>
                        </div>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
              {!!count && (
                <div className="basket">
                  <div>
                    <span className="eyebrow">ВАША КОРЗИНА</span>
                    <strong>{count} шт.</strong>
                  </div>
                  <button onClick={review} disabled={busy}>
                    {busy ? "Загружаем…" : "Выбрать время →"}
                  </button>
                </div>
              )}
            </>
          )}
          {view === "review" && (
            <section className="review">
              {pending ? (
                <>
                  <h3>Проверяем оформление</h3>
                  <p>
                    Если ответ не пришёл, повторите подтверждение. Повторный
                    запрос вернёт тот же заказ.
                  </p>
                  <p>Сумма: {money(pending.expected_total_minor)}</p>
                  <button disabled={busy} onClick={confirm}>
                    {busy ? "Проверяем…" : "Повторить подтверждение"}
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="quiet"
                    disabled={busy}
                    onClick={() => setView("menu")}
                  >
                    ← Изменить напитки
                  </button>
                  {preview && <OrderLines order={preview} />}
                  <h3>Когда вам удобно?</h3>
                  <p>Место бронируется при подтверждении заказа.</p>
                  <div className="slots">
                    {slots.map((x) => (
                      <button
                        className={x.id === slotId ? "selected" : ""}
                        key={x.id}
                        disabled={busy}
                        onClick={() => setSlotId(x.id)}
                      >
                        {time(
                          x.starts_at,
                          cafe?.timezone ?? "Asia/Novosibirsk",
                        )}
                        <small>Свободно: {x.available}</small>
                      </button>
                    ))}
                  </div>
                  {slots.length === 0 && (
                    <p>
                      Свободного времени пока нет.{" "}
                      <button
                        className="quiet"
                        disabled={busy}
                        onClick={review}
                      >
                        Обновить время
                      </button>
                    </p>
                  )}
                  <button
                    className="confirm"
                    disabled={busy || !slotId}
                    onClick={confirm}
                  >
                    {busy ? "Оформляем…" : "Подтвердить заказ →"}
                  </button>
                </>
              )}
            </section>
          )}
        </>
      )}
      <footer>
        <span>cofmart</span>
        <p>Хороший день начинается с маленькой чашки.</p>
      </footer>
    </main>
  );
}

function OrderLines({ order }: { order: Preview }) {
  return (
    <div className="lines">
      {order.items.map((x) => (
        <div key={x.menu_item_id}>
          <span>
            {x.name} × {x.quantity}
          </span>
          <span>{money(x.price_minor * x.quantity)}</span>
        </div>
      ))}
      <div className="total">
        <strong>Итого</strong>
        <strong>{money(order.total_minor)}</strong>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
