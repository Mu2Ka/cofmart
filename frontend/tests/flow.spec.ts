import {test, expect, Page} from '@playwright/test';

async function app(page: Page, options: {paused?:boolean,staff?:boolean,resumed?:boolean}={}) {
  const slots = {limit:10,free:10,reserved:0,confirmed:0,revision:0,active:0,completed:0};
  const periods = [{id:'20310102-1s-live',label:'Выдача по готовности'}];
  const product = {id:'1',name:'Американо',category:'coffee',sizes:{'350':165},alternative_milk:false,
    available:true,variants:{'1_350':{name:'Американо · 350 мл',price:165}}};
  const state:any = {user_id:1001,admin:false,staff_cafes:options.staff?['1']:[],categories:{coffee:'Кофе'},
    cafes:[{id:'1',name:'CaVa',open:true,slots:options.paused?null:{...slots},products:[product]}],
    periods:options.paused?[]:periods,follow_schedule:true,schedule_message:'Приём возобновим в 09:50',
    pauses:['09:40–09:50'],session:'',draft:null,orders:[],favorites:[],summaries:{}};
  const requests:any[]=[];
  const controls={state, requests, periods, rejected:0, previousFailure:false, dropConfirmation:false};
  let session = 0, token = 0;
  const makeDraft=()=>({token:`token-${++token}`,cafe_id:'1',drink_id:'1_350',cafe_name:'CaVa',
    drink_name:'Американо · 350 мл',price:165,comment:'',reserved_until:new Date(Date.now()+120000).toISOString(),
    pickup_label:'Выдача по готовности'});
  if(options.resumed) {state.session='session1';state.draft={...makeDraft(),comment:'без сахара'};}
  await page.clock.install();
  await page.route('https://telegram.org/**', route=>route.fulfill({body:'',contentType:'application/javascript'}));
  await page.addInitScript(()=>{
    (window as any).Telegram={WebApp:{initData:'signed-test-data',ready(){},expand(){}}};
  });
  await page.route('**/api/**',async route=>{
    if(controls.rejected) return route.fulfill({status:controls.rejected,json:{detail:'Сессия истекла. Откройте приложение заново.'}});
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/flow/state') return route.fulfill({json:state});
    if(path==='/api/orders') return route.fulfill(controls.previousFailure
      ? {status:503,json:{detail:'Архив временно недоступен'}} : {json:[]});
    if(path==='/api/flow/staff/1') return route.fulfill({json:{orders:[],periods:[{...state.cafes[0].slots,
      id:periods[0].id,label:'Текущий период'}],rating_count:0,rating_average:null,baristas:[1001]}});
    const body=route.request().postDataJSON(); requests.push(body);
    let result:any=null;
    switch(body.action) {
      case 'begin': state.draft=null;state.session=`session${++session}`;result=state.session;break;
      case 'cancel':
        if(body.session!==state.session) return route.fulfill({status:409,json:{detail:'Оформление устарело'}});
        state.draft=null;state.session='';break;
      case 'prepare':
        if(!body.session || body.session!==state.session) return route.fulfill({status:409,json:{detail:'Оформление устарело'}});
        state.draft=makeDraft();result=state.draft;break;
      case 'comment':state.draft={...state.draft,token:`token-${++token}`,comment:body.comment.trim()};result=state.draft;break;
      case 'confirm':
        if(body.token!==state.draft?.token) return route.fulfill({status:409,json:{detail:'Карточка устарела'}});
        result={number:1,reference:'1-reference',draft:state.draft,status:'new',status_label:'Новый',revision:0,
          rating:null,barista_id:null,transitions:[],created_at:new Date().toISOString()};
        state.orders.unshift(result);state.draft=null;state.session='';
        if(controls.dropConfirmation) return route.abort('connectionreset');
        break;
      case 'add_slots':state.cafes[0].slots.limit+=body.value;state.cafes[0].slots.free+=body.value;
        state.cafes[0].slots.revision++;break;
      default:throw new Error(`Unexpected action ${body.action}`);
    }
    return route.fulfill({json:{result}});
  });
  await page.goto('/');
  await expect(page.getByText('Ваш Telegram ID: 1001')).toBeVisible();
  return controls;
}

async function selectDrink(page:Page, start=true) {
  if(start) await page.getByRole('button',{name:'🎓 Студент · заказать кофе'}).click();
  await page.locator('.cafe').filter({hasText:'CaVa'}).click();
  await page.getByRole('button',{name:'Кофе',exact:true}).click();
  await page.getByRole('button',{name:/Американо/}).click();
  await page.getByRole('button',{name:/350 мл/}).click();
  await expect(page.getByRole('heading',{name:'🧾 Проверьте заказ'})).toBeVisible();
}

test('confirmation saves typed wishes and confirms the new token',async({page})=>{
  const api=await app(page);await selectDrink(page);
  await page.getByRole('textbox').fill('со льдом <много>');
  await page.getByRole('button',{name:'✓ Подтвердить заказ'}).click();
  await expect(page.locator('.order')).toContainText('со льдом <много>');
  expect(api.requests.slice(-2).map(x=>x.action)).toEqual(['comment','confirm']);
  expect(api.state.orders[0].draft.comment).toBe('со льдом <много>');
});

test('clearing a saved comment actually removes it',async({page})=>{
  const api=await app(page,{resumed:true});
  await page.getByRole('button',{name:'Продолжить оформление'}).click();
  await page.getByRole('textbox').fill('');
  await page.getByRole('button',{name:'✓ Подтвердить заказ'}).click();
  await expect(page.locator('.order')).toContainText('Без пожеланий');
  expect(api.state.orders[0].draft.comment).toBe('');
});

test('lost confirmation response recovers the saved order without a second checkout',async({page})=>{
  const api=await app(page);await selectDrink(page);api.dropConfirmation=true;
  await page.getByRole('button',{name:'✓ Подтвердить заказ'}).click();
  await expect(page.locator('.order')).toContainText('Заказ №1');
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(api.requests.filter(x=>x.action==='confirm')).toHaveLength(1);
});

test('comment length uses the same Unicode characters as Python',async({page})=>{
  const api=await app(page);await selectDrink(page);
  const text='🧊'.repeat(300);
  await page.getByRole('textbox').fill(text);
  await expect(page.getByText('300/300')).toBeVisible();
  await page.getByRole('button',{name:'✓ Подтвердить заказ'}).click();
  await expect(page.locator('.order')).toBeVisible();
  expect(api.state.orders[0].draft.comment).toBe(text);
});

test('leaving a draft releases the reservation',async({page})=>{
  const api=await app(page);await selectDrink(page);
  await page.getByRole('button',{name:'Роли',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Выберите, как продолжить'})).toBeVisible();
  expect(api.state.draft).toBeNull();
  expect(api.requests.at(-1).action).toBe('cancel');
});

test('a cancelled draft can be followed by a new order without stale session',async({page})=>{
  const api=await app(page);await selectDrink(page);
  await page.getByRole('button',{name:'✕ Отменить',exact:true}).click();
  await selectDrink(page,false);
  expect(api.state.draft).not.toBeNull();
  expect(api.requests.map(x=>x.action)).toEqual(['begin','prepare','cancel','begin','prepare']);
});

test('schedule pause refreshes automatically without reopening the app',async({page})=>{
  const api=await app(page,{paused:true});
  await page.getByRole('button',{name:'🎓 Студент · заказать кофе'}).click();
  await expect(page.getByText('Пауза по расписанию')).toBeVisible();
  api.state.periods=api.periods;api.state.cafes[0].slots={limit:10,free:10};
  await page.clock.fastForward(15000);
  await expect(page.getByText('Приём открыт',{exact:true})).toBeVisible();
});

test('revoked barista role clears the working panel on refresh',async({page})=>{
  const api=await app(page,{staff:true});
  await page.getByRole('button',{name:'☕ Бариста · рабочая панель'}).click();
  await page.getByRole('button',{name:/CaVa · приём открыт/}).click();
  await expect(page.getByRole('heading',{name:'🎟 Слоты приёма'})).toBeVisible();
  api.state.staff_cafes=[];
  await page.clock.fastForward(15000);
  await expect(page.getByText(/Доступ не назначен/)).toBeVisible();
  await expect(page.getByRole('button',{name:'+5 слотов'})).toHaveCount(0);
});

test('archive failure is visible and does not produce unhandled errors',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  const api=await app(page);api.previousFailure=true;
  await page.getByRole('button',{name:'Мои заказы ↗'}).click();
  await page.getByRole('button',{name:'Заказы ранней версии'}).click();
  await expect(page.getByRole('alert')).toContainText('Архив временно недоступен');
  expect(errors).toEqual([]);
});

test('expired authorization hides cached private state',async({page})=>{
  const api=await app(page);api.rejected=401;
  await page.clock.fastForward(15000);
  await expect(page.getByRole('alert')).toContainText('Сессия истекла');
  await expect(page.getByText('Ваш Telegram ID: 1001')).toHaveCount(0);
});

test('empty quota is not silently submitted as zero and overflow buttons are disabled',async({page})=>{
  const api=await app(page,{staff:true});
  api.state.cafes[0].slots.limit=999;
  await page.getByRole('button',{name:'☕ Бариста · рабочая панель'}).click();
  await page.getByRole('button',{name:/CaVa · приём открыт/}).click();
  await expect(page.getByRole('button',{name:'+1 слот',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'+5 слотов'})).toBeDisabled();
  await page.getByRole('spinbutton').fill('');
  await expect(page.getByRole('button',{name:'Установить лимит'})).toBeDisabled();
  expect(api.requests.filter(x=>x.action==='set_slots')).toHaveLength(0);
});

test('double-clicking additional capacity sends one mutation',async({page})=>{
  const api=await app(page,{staff:true});
  await page.getByRole('button',{name:'☕ Бариста · рабочая панель'}).click();
  await page.getByRole('button',{name:/CaVa · приём открыт/}).click();
  await page.getByRole('button',{name:'+5 слотов'}).evaluate((button:HTMLButtonElement)=>{button.click();button.click();});
  await expect(page.getByText(/Свободно 15\/15/)).toBeVisible();
  expect(api.requests.filter(x=>x.action==='add_slots')).toHaveLength(1);
});

test('the first click after a pause fetches the new period immediately',async({page})=>{
  const api=await app(page,{paused:true});
  await page.getByRole('button',{name:'🎓 Студент · заказать кофе'}).click();
  await page.locator('.cafe').click();
  await page.getByRole('button',{name:'Кофе',exact:true}).click();
  await page.getByRole('button',{name:/Американо/}).click();
  api.state.periods=api.periods;
  await page.getByRole('button',{name:/350 мл/}).click();
  await expect(page.getByRole('heading',{name:'🧾 Проверьте заказ'})).toBeVisible();
  expect(api.requests.at(-1).break_id).toBe(api.periods[0].id);
});
