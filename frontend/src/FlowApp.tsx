import { useEffect, useRef, useState } from "react";
import { initData } from "./telegram";
import {
  act,
  loadState,
  loadStaff,
  type State,
  type Staff,
  type Product,
  type Order,
} from "./flow-api";

type View =
  | "roles"
  | "cafes"
  | "categories"
  | "products"
  | "sizes"
  | "milk"
  | "draft"
  | "orders"
  | "favorites"
  | "schedule"
  | "staff"
  | "admin"
  | "previous";
const rub = (n: number) =>
  new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format(n);
const sizeLabel = (size: string) =>
  size === "portion" ? "порция" : `${size} мл`;
const clock = (date: string) =>
  new Date(date).toLocaleTimeString("ru-RU", {
    timeZone: "Asia/Novosibirsk",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

export default function FlowApp() {
  const [state, setState] = useState<State | null>(null);
  const [view, setView] = useState<View>("roles");
  const [cafeId, setCafeId] = useState("1");
  const [category, setCategory] = useState("coffee");
  const [product, setProduct] = useState<Product | null>(null);
  const [size, setSize] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [staff, setStaff] = useState<Staff | null>(null);
  const [filter, setFilter] = useState("active");
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState<Record<string, string>>({});
  const [target, setTarget] = useState("");
  const [previous, setPrevious] = useState<
    {
      id: number;
      cafe_name: string;
      total_minor: number;
      items: { name: string; quantity: number }[];
    }[]
  >([]);
  const inFlight = useRef(false);
  const cafe = state?.cafes.find((c) => c.id === cafeId);
  const roleAccess = !!state?.staff_cafes.includes(cafeId);

  async function refresh() {
    const next = await loadState();
    setState(next);
    return next;
  }
  useEffect(() => {
    if (initData) refresh().catch((e) => setError(e.message));
  }, []);
  async function run(
    action: string,
    values: Record<string, unknown> = {},
    next?: View,
  ) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await act(action, values);
      const data = await refresh();
      if (next) setView(next);
      if (next === "draft") setComment(data.draft?.comment ?? "");
      if (action === "confirm")
        setNotice("Заказ подтверждён. Оплата пока не подключена.");
      if (view === "staff" && data.staff_cafes.includes(cafeId))
        setStaff(await loadStaff(cafeId));
      return true;
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Не удалось выполнить действие.",
      );
      return false;
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  async function openStaff(id: string) {
    setBusy(true);
    setError("");
    try {
      setStaff(await loadStaff(id));
      setCafeId(id);
      setView("staff");
      setPage(0);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function chooseSku(sku: string) {
    if (!state?.periods.length) {
      setError(state?.schedule_message ?? "Приём закрыт");
      return;
    }
    await run(
      "prepare",
      {
        cafe_id: cafeId,
        drink_id: sku,
        break_id: state.periods[0].id,
        session: state.session,
        comment: "",
      },
      "draft",
    );
    setComment("");
  }
  async function newOrder() {
    await run("begin", {}, "cafes");
    setComment("");
    setProduct(null);
  }
  function navigate(next: View) {
    setView(next);
    setPage(0);
    setError("");
    setNotice("");
  }

  if (!initData)
    return (
      <main className="welcome">
        <span className="mark">c.</span>
        <h1>
          Ваш кофе.
          <br />В ваше время.
        </h1>
        <p>Откройте Mini App через кнопку «Заказать кофе» в Telegram-боте.</p>
      </main>
    );
  return (
    <main>
      <header>
        <button className="brand quiet" onClick={() => navigate("roles")}>
          cofmart<span>●</span>
        </button>
        <button
          className="quiet"
          disabled={busy}
          onClick={() => {
            navigate("orders");
            refresh().catch((e) => setError(e.message));
          }}
        >
          Мои заказы ↗
        </button>
      </header>
      <section className="flow-intro">
        <span className="eyebrow">КОФЕ К ТВОЕМУ ПЕРЕРЫВУ</span>
        <h1>☕ Cofmart</h1>
        {state && <p className="muted">Ваш Telegram ID: {state.user_id}</p>}
      </section>
      {error && (
        <div className="notice" role="alert">
          {error}
          <button
            className="quiet"
            onClick={() =>
              refresh()
                .then(() => setError(""))
                .catch((e) => setError(e.message))
            }
          >
            Обновить
          </button>
        </div>
      )}
      {notice && (
        <div className="local-notice" role="status">
          {notice}
        </div>
      )}
      {!state && !error && <p role="status">Загружаем меню…</p>}
      {state && (
        <fieldset className="flow-fieldset" disabled={busy}>
          {view === "roles" && (
            <section>
              <h2>Выберите, как продолжить</h2>
              <div className="flow-actions">
                <button onClick={newOrder}>🎓 Студент · заказать кофе</button>
                {!!state.staff_cafes.length && (
                  <button
                    onClick={() => {
                      setView("admin");
                      setPage(0);
                    }}
                  >
                    ☕ Бариста · рабочая панель
                  </button>
                )}
                {state.admin && (
                  <button onClick={() => navigate("admin")}>
                    ⚙ Администратор
                  </button>
                )}
                <button
                  className="secondary"
                  onClick={() => navigate("favorites")}
                >
                  ⭐ Избранные напитки
                </button>
                <button
                  className="secondary"
                  onClick={() => {
                    const last = state.orders[0];
                    if (last)
                      run("repeat", { reference: last.reference }, "draft");
                    else setNotice("У вас пока нет заказов для повторения.");
                  }}
                >
                  ↻ Повторить прошлый заказ
                </button>
                <button
                  className="secondary"
                  onClick={() => navigate("schedule")}
                >
                  Расписание и режим приёма
                </button>
                {state.draft && (
                  <button
                    onClick={() => {
                      setComment(state.draft?.comment ?? "");
                      navigate("draft");
                    }}
                  >
                    Продолжить оформление
                  </button>
                )}
              </div>
            </section>
          )}
          {view === "cafes" && (
            <section>
              <div className="section-title">
                <h2>☕ Заказ кофе</h2>
                <button className="quiet" onClick={newOrder}>
                  ↻ Обновить слоты
                </button>
              </div>
              <p>{state.periods[0]?.label ?? state.schedule_message}</p>
              <p className="muted">Выберите кофейню для просмотра меню:</p>
              <div className="cafes">
                {state.cafes.map((c) => (
                  <button
                    className="cafe"
                    key={c.id}
                    onClick={() => {
                      setCafeId(c.id);
                      navigate("categories");
                    }}
                  >
                    <span>КОФЕЙНЯ</span>
                    <strong>{c.name}</strong>
                    <span>
                      {c.open ? "Приём открыт" : "⏸ Приём остановлен"}
                    </span>
                    <span>
                      Свободно {c.open ? (c.slots?.free ?? 0) : 0}/
                      {c.slots?.limit ?? 0} слотов
                    </span>
                  </button>
                ))}
              </div>
              <button className="quiet" onClick={() => navigate("roles")}>
                ← Выбор роли
              </button>
            </section>
          )}
          {["categories", "products", "sizes", "milk"].includes(view) && (
            <section>
              <div className="section-title">
                <h2>{cafe?.name}</h2>
                <button className="quiet" onClick={() => navigate("cafes")}>
                  ← Кофейни
                </button>
              </div>
              {!cafe?.open && (
                <p className="local-notice">
                  Кофейня временно остановила приём. Меню доступно для
                  просмотра.
                </p>
              )}
              {view === "categories" && (
                <>
                  <p>Что приготовим? Выберите раздел:</p>
                  <div className="flow-actions">
                    {Object.entries(state.categories)
                      .filter(([key]) =>
                        cafe?.products.some((p) => p.category === key),
                      )
                      .map(([key, name]) => (
                        <button
                          key={key}
                          onClick={() => {
                            setCategory(key);
                            navigate("products");
                          }}
                        >
                          {name}
                        </button>
                      ))}
                  </div>
                </>
              )}
              {view === "products" && (
                <>
                  <h3>{state.categories[category]}</h3>
                  <p>Выберите напиток:</p>
                  <div className="product-list">
                    {cafe?.products
                      .filter((p) => p.category === category && p.available)
                      .map((p) => (
                        <button
                          className="product-row"
                          key={p.id}
                          onClick={() => {
                            setProduct(p);
                            navigate("sizes");
                          }}
                        >
                          <strong>{p.name}</strong>
                          <span>
                            {Object.keys(p.sizes).length > 1 ? "от " : ""}
                            {rub(Math.min(...Object.values(p.sizes)))} →
                          </span>
                        </button>
                      ))}
                  </div>
                  {!cafe?.products.some(
                    (p) => p.category === category && p.available,
                  ) && <p>В этом разделе пока нет доступных напитков.</p>}
                  <button
                    className="quiet"
                    onClick={() => navigate("categories")}
                  >
                    ← Разделы меню
                  </button>
                </>
              )}
              {view === "sizes" && product && (
                <>
                  <h3>{product.name}</h3>
                  <p>Выберите объём:</p>
                  <div className="flow-actions">
                    {Object.entries(product.sizes).map(([key, price]) => (
                      <button
                        key={key}
                        onClick={() => {
                          setSize(key);
                          if (product.alternative_milk) navigate("milk");
                          else chooseSku(`${product.id}_${key}`);
                        }}
                      >
                        {sizeLabel(key)} · {rub(price)}
                      </button>
                    ))}
                  </div>
                  <button
                    className="quiet"
                    onClick={() => navigate("products")}
                  >
                    ← Напитки
                  </button>
                </>
              )}
              {view === "milk" && product && (
                <>
                  <h3>
                    {product.name} · {sizeLabel(size)}
                  </h3>
                  <p>Выберите молоко:</p>
                  <div className="flow-actions">
                    <button onClick={() => chooseSku(`${product.id}_${size}`)}>
                      Обычное молоко · {rub(product.sizes[size])}
                    </button>
                    <button onClick={() => chooseSku(`${product.id}_${size}a`)}>
                      Альтернативное молоко ·{" "}
                      {rub(
                        product.variants[product.id + "_" + size + "a"].price,
                      )}
                    </button>
                  </div>
                  <button className="quiet" onClick={() => navigate("sizes")}>
                    ← Объём
                  </button>
                </>
              )}
            </section>
          )}
          {view === "draft" &&
            (state.draft ? (
              <section className="review">
                <h2>🧾 Проверьте заказ</h2>
                <h3>{state.draft.cafe_name}</h3>
                <p>{state.draft.drink_name}</p>
                <p>💬 {state.draft.comment || "Без пожеланий"}</p>
                <div className="lines">
                  <div className="total">
                    <strong>Итого</strong>
                    <strong>{rub(state.draft.price)}</strong>
                  </div>
                </div>
                <p>{state.draft.pickup_label}</p>
                <p>
                  Один слот зарезервирован до{" "}
                  <strong>{clock(state.draft.reserved_until)}</strong>{" "}
                  (Новосибирск).
                </p>
                <label className="field">
                  Добавить / изменить комментарий
                  <textarea
                    maxLength={300}
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="Например: американо со льдом"
                  />
                  <small>{comment.length}/300</small>
                </label>
                <div className="flow-actions">
                  <button
                    className="secondary"
                    onClick={() =>
                      run(
                        "comment",
                        { token: state.draft!.token, comment },
                        "draft",
                      )
                    }
                  >
                    Сохранить пожелания
                  </button>
                  <button
                    className="secondary"
                    onClick={() => {
                      setComment(state.draft?.comment ?? "");
                      setNotice("Комментарий оставлен без изменений.");
                    }}
                  >
                    Оставить как есть
                  </button>
                  <button
                    onClick={() =>
                      run("confirm", { token: state.draft!.token }, "orders")
                    }
                  >
                    ✓ Подтвердить заказ
                  </button>
                  <button
                    className="secondary"
                    onClick={() =>
                      run("favorite_draft", { token: state.draft!.token }).then(
                        (ok) => {
                          if (ok) setNotice("Напиток добавлен в избранное ⭐");
                        },
                      )
                    }
                  >
                    ⭐ В избранное
                  </button>
                  <button
                    className="quiet"
                    onClick={() =>
                      run("cancel", { session: state.session }, "cafes")
                    }
                  >
                    ✕ Отменить
                  </button>
                </div>
                <p className="muted">
                  Тестовый заказ. Оплата пока не подключена.
                </p>
              </section>
            ) : (
              <section>
                <p>Резерв истёк или оформление завершено.</p>
                <button onClick={newOrder}>Новый заказ</button>
              </section>
            ))}
          {view === "orders" && (
            <section>
              <div className="section-title">
                <h2>📋 Мои заказы</h2>
                <button
                  className="quiet"
                  onClick={() => refresh().catch((e) => setError(e.message))}
                >
                  ↻ Обновить
                </button>
              </div>
              {!state.orders.length && <p>Заказов пока нет.</p>}
              {state.orders.slice(page * 5, page * 5 + 5).map((order) => (
                <OrderCard key={order.reference} order={order}>
                  <div className="flow-actions">
                    <button
                      onClick={() =>
                        run("repeat", { reference: order.reference }, "draft")
                      }
                    >
                      ↻ Повторить этот заказ
                    </button>
                    <button
                      className="secondary"
                      onClick={() =>
                        run("favorite_order", {
                          reference: order.reference,
                        }).then((ok) => {
                          if (ok) setNotice("Напиток добавлен в избранное ⭐");
                        })
                      }
                    >
                      ⭐ В избранное
                    </button>
                    {order.status === "done" && (
                      <div className="rating" aria-label="Оценить заказ">
                        {[1, 2, 3, 4, 5].map((n) => (
                          <button
                            key={n}
                            className={
                              order.rating === n ? "selected" : "secondary"
                            }
                            onClick={() =>
                              run("rate", {
                                reference: order.reference,
                                value: n,
                              })
                            }
                          >
                            {n} ⭐
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </OrderCard>
              ))}
              <Pages
                page={page}
                size={5}
                count={state.orders.length}
                onChange={setPage}
              />
              <button
                className="quiet"
                onClick={async () => {
                  const { request } = await import("./api");
                  setPrevious(await request("/orders"));
                  navigate("previous");
                }}
              >
                Заказы ранней версии
              </button>
            </section>
          )}
          {view === "previous" && (
            <section>
              <h2>Заказы ранней версии</h2>
              {!previous.length && <p>Заказов пока нет.</p>}
              {previous.map((order) => (
                <article className="order" key={order.id}>
                  <h3>
                    Заказ №{order.id} · {order.cafe_name}
                  </h3>
                  {order.items.map((line, i) => (
                    <p key={i}>
                      {line.name} × {line.quantity}
                    </p>
                  ))}
                  <strong>{rub(order.total_minor / 100)}</strong>
                </article>
              ))}
              <button className="quiet" onClick={() => navigate("orders")}>
                ← Мои заказы
              </button>
            </section>
          )}
          {view === "favorites" && (
            <section>
              <h2>⭐ Избранные напитки</h2>
              <p>{state.favorites.length}/30 вариантов</p>
              {!state.favorites.length && (
                <p>
                  Пока пусто. Нажмите «В избранное» в карточке напитка или
                  заказа.
                </p>
              )}
              {state.favorites.slice(page * 6, page * 6 + 6).map((f) => (
                <article className="order" key={f.key}>
                  <h3>{f.cafe_name}</h3>
                  <p>{f.drink_name}</p>
                  <div className="flow-actions">
                    <button
                      onClick={() =>
                        run("favorite_prepare", { key: f.key }, "draft")
                      }
                    >
                      ☕ Заказать по текущей цене
                    </button>
                    <button
                      className="quiet"
                      onClick={() => run("favorite_remove", { key: f.key })}
                    >
                      Удалить из избранного
                    </button>
                  </div>
                </article>
              ))}
              <Pages
                page={page}
                size={6}
                count={state.favorites.length}
                onChange={setPage}
              />
            </section>
          )}
          {view === "schedule" && (
            <section className="review">
              <h2>Расписание и режим</h2>
              <p>
                {state.follow_schedule
                  ? "Приём с паузами на короткие перерывы"
                  : "🧪 Тестовый режим · паузы отключены"}
              </p>
              <p>{state.schedule_message}</p>
              <h3>Паузы приёма (Новосибирск)</h3>
              {state.pauses.map((p) => (
                <p key={p}>{p}</p>
              ))}
              <p>Меню, история заказов и рабочая панель доступны постоянно.</p>
            </section>
          )}
          {view === "admin" && (
            <section>
              <h2>
                {state.admin
                  ? "⚙ Панель администратора"
                  : "☕ Рабочая панель баристы"}
              </h2>
              <p>Выберите кофейню:</p>
              <div className="flow-actions">
                {state.cafes
                  .filter((c) => state.staff_cafes.includes(c.id))
                  .map((c) => (
                    <button key={c.id} onClick={() => openStaff(c.id)}>
                      {c.name} · {c.open ? "приём открыт" : "приём остановлен"}
                      {state.summaries[c.id] && (
                        <small className="summary-counts">
                          {Object.entries(state.summaries[c.id])
                            .map(([label, count]) => `${label}: ${count}`)
                            .join(" · ")}
                        </small>
                      )}
                    </button>
                  ))}
              </div>
              {!state.staff_cafes.length && (
                <p>
                  Доступ не назначен. Сообщите администратору свой Telegram ID:{" "}
                  {state.user_id}.
                </p>
              )}
            </section>
          )}
          {view === "staff" && roleAccess && staff && (
            <section>
              <div className="section-title">
                <h2>☕ {cafe?.name}</h2>
                <button className="quiet" onClick={() => openStaff(cafeId)}>
                  ↻ Обновить
                </button>
              </div>
              <p>
                {cafe?.open ? "🟢 Приём открыт" : "⏸ Приём остановлен"} · ⭐{" "}
                {staff.rating_average?.toFixed(1) ?? "нет оценок"} (
                {staff.rating_count})
              </p>
              <button
                className="secondary"
                onClick={() =>
                  run("set_open", { cafe_id: cafeId, enabled: !cafe?.open })
                }
              >
                {cafe?.open ? "⏸ Остановить приём" : "▶ Возобновить приём"}
              </button>
              <h3 className="flow-heading">📋 Очередь</h3>
              <div className="tabs">
                {Object.entries({
                  active: "Активные",
                  new: "Новые",
                  preparing: "Готовятся",
                  ready: "Готовы",
                  done: "Выданные",
                  cancelled: "Отменённые",
                }).map(([key, name]) => (
                  <button
                    className={filter === key ? "" : "secondary"}
                    key={key}
                    onClick={() => {
                      setFilter(key);
                      setPage(0);
                    }}
                  >
                    {name}
                  </button>
                ))}
              </div>
              {staff.orders
                .filter((o) =>
                  filter === "active"
                    ? ["new", "preparing", "ready"].includes(o.status)
                    : o.status === filter,
                )
                .slice(page * 6, page * 6 + 6)
                .map((o) => (
                  <OrderCard order={o} key={o.reference}>
                    <p>Бариста: {o.barista_id ?? "Ещё не взят в работу"}</p>
                    <div className="flow-actions">
                      {(state.admin ||
                        o.barista_id === null ||
                        o.barista_id === state.user_id) &&
                        Object.entries({
                          preparing: "☕ Взять в работу",
                          ready: "✅ Готов",
                          done: "📦 Выдан",
                          cancelled: "✕ Отменить заказ",
                        })
                          .filter(([status]) => o.transitions.includes(status))
                          .map(([status, label]) => (
                            <button
                              key={status}
                              onClick={() =>
                                run("transition", {
                                  reference: o.reference,
                                  status,
                                  revision: o.revision,
                                })
                              }
                            >
                              {label}
                            </button>
                          ))}
                    </div>
                  </OrderCard>
                ))}
              <Pages
                page={page}
                size={6}
                count={
                  staff.orders.filter((o) =>
                    filter === "active"
                      ? ["new", "preparing", "ready"].includes(o.status)
                      : o.status === filter,
                  ).length
                }
                onChange={setPage}
              />
              <h3 className="flow-heading">🎟 Слоты приёма</h3>
              {staff.periods.map((p) => (
                <article className="order" key={p.id}>
                  <h3>{p.label}</h3>
                  <p>
                    Свободно {p.free}/{p.limit} · в работе {p.active} · выдано{" "}
                    {p.completed} · резервы {p.reserved}
                  </p>
                  <div className="tabs">
                    {[1, 5].map((value) => (
                      <button
                        key={value}
                        onClick={() =>
                          run("add_slots", {
                            cafe_id: cafeId,
                            break_id: p.id,
                            value,
                            revision: p.revision,
                          })
                        }
                      >
                        +{value} {value === 1 ? "слот" : "слотов"}
                      </button>
                    ))}
                  </div>
                  <label className="field">
                    Общий лимит (0–999)
                    <input
                      type="number"
                      min={0}
                      max={999}
                      value={limit[p.id] ?? String(p.limit)}
                      onChange={(e) =>
                        setLimit({ ...limit, [p.id]: e.target.value })
                      }
                    />
                  </label>
                  <button
                    className="secondary"
                    onClick={() =>
                      run("set_slots", {
                        cafe_id: cafeId,
                        break_id: p.id,
                        value: Number(limit[p.id] ?? p.limit),
                        revision: p.revision,
                      })
                    }
                  >
                    Установить лимит
                  </button>
                  <p className="muted">
                    Выдача заказа не возвращает слот. Чтобы принять больше
                    заказов, добавьте слоты.
                  </p>
                </article>
              ))}
              <h3 className="flow-heading">🥤 Наличие напитков</h3>
              <div className="product-list">
                {cafe?.products.map((p) => (
                  <button
                    className="product-row"
                    key={p.id}
                    onClick={() =>
                      run("set_available", {
                        cafe_id: cafeId,
                        product_id: p.id,
                        enabled: !p.available,
                      })
                    }
                  >
                    <span>
                      {p.available ? "✅" : "⛔"} {p.name}
                    </span>
                    <span>{p.available ? "Выключить" : "Включить"}</span>
                  </button>
                ))}
              </div>
              {state.admin && (
                <section className="review">
                  <h3>Назначение барист</h3>
                  <p>Баристы: {staff.baristas.join(", ") || "не назначены"}</p>
                  <label className="field">
                    Telegram ID сотрудника
                    <input
                      inputMode="numeric"
                      value={target}
                      onChange={(e) => setTarget(e.target.value)}
                    />
                  </label>
                  <div className="flow-actions">
                    <button
                      disabled={!/^[1-9]\d*$/.test(target)}
                      onClick={() =>
                        run("assign", {
                          cafe_id: cafeId,
                          target_id: Number(target),
                          enabled: true,
                        })
                      }
                    >
                      Назначить баристу
                    </button>
                    <button
                      className="secondary"
                      disabled={!/^[1-9]\d*$/.test(target)}
                      onClick={() =>
                        run("assign", {
                          cafe_id: cafeId,
                          target_id: Number(target),
                          enabled: false,
                        })
                      }
                    >
                      Снять доступ
                    </button>
                  </div>
                </section>
              )}
              <button className="quiet" onClick={() => navigate("admin")}>
                ← Рабочие кофейни
              </button>
            </section>
          )}
          <nav className="bottom-nav" aria-label="Навигация">
            <button className="quiet" onClick={() => navigate("roles")}>
              Роли
            </button>
            <button className="quiet" onClick={newOrder}>
              Новый заказ
            </button>
            <button className="quiet" onClick={() => navigate("orders")}>
              Мои заказы
            </button>
            <button className="quiet" onClick={() => navigate("favorites")}>
              Избранное
            </button>
          </nav>
        </fieldset>
      )}
      <footer>
        <span>cofmart</span>
        <p>Хороший день начинается с маленькой чашки.</p>
      </footer>
    </main>
  );
}

function OrderCard({
  order,
  children,
}: {
  order: Order;
  children?: React.ReactNode;
}) {
  return (
    <article className="order">
      <span className="eyebrow">
        Заказ №{order.number} · {order.status_label}
      </span>
      <h3>{order.draft.cafe_name}</h3>
      <p>{order.draft.drink_name}</p>
      <p>💬 {order.draft.comment || "Без пожеланий"}</p>
      <strong>{rub(order.draft.price)}</strong>
      <p>{order.draft.pickup_label}</p>
      {order.rating !== null && <p>⭐ Оценка: {order.rating}/5</p>}
      {children}
    </article>
  );
}
function Pages({
  page,
  size,
  count,
  onChange,
}: {
  page: number;
  size: number;
  count: number;
  onChange: (n: number) => void;
}) {
  return count > size ? (
    <div className="tabs">
      <button disabled={!page} onClick={() => onChange(page - 1)}>
        ←
      </button>
      <span>
        Страница {page + 1} / {Math.ceil(count / size)}
      </span>
      <button
        disabled={(page + 1) * size >= count}
        onClick={() => onChange(page + 1)}
      >
        →
      </button>
    </div>
  ) : null;
}
