import os, hmac, hashlib, json, asyncio, sqlite3, secrets, datetime as dt
from urllib.parse import parse_qsl
from aiohttp import web, WSMsgType
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton,
                           WebAppInfo, MenuButtonWebApp)

TOKEN = os.environ["BOT_TOKEN"]
BASE = os.environ["BASE_URL"].rstrip("/")
PORT = int(os.getenv("PORT", 8080))
PUSH_HOUR = int(os.getenv("PUSH_HOUR", 9))
bot, dp, BOTNAME = Bot(TOKEN), Dispatcher(), ""

db = sqlite3.connect("data.db", check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
create table if not exists users(id integer primary key, name text, couple integer, code text, token text);
create table if not exists couples(id integer primary key autoincrement, a integer, b integer, start text);
create table if not exists done(couple integer, day text, user integer, primary key(couple,day,user));
create table if not exists wishes(id integer primary key autoincrement, owner integer, title text, link text, reserved_by integer);
""")

def q(sql, *a): return db.execute(sql, a).fetchall()
def ex(sql, *a):
    cur = db.execute(sql, a); db.commit(); return cur.lastrowid

TASKS = [
 "Напиши партнеру 3 речі, за які ти вдячний/вдячна сьогодні",
 "Надішли голосове з побажанням гарного дня",
 "Згадайте разом ваше перше побачення — що ви пам'ятаєте?",
 "Приготуй для партнера улюблений чай або каву",
 "Зроби фото того, що нагадало тобі про нього/неї, і надішли",
 "Обійміться на 20 секунд без телефонів",
 "Запропонуй місце, куди хочеш поїхати разом цього року",
 "Напиши короткий лист-зізнання (3 речення)",
 "Влаштуйте вечір без гаджетів: настолка або прогулянка",
 "Скажи партнеру, що саме тобі в ньому/ній подобається найбільше",
 "Обери фільм на вечір і подивіться разом у розділі «Кіно»",
 "Зробіть селфі-пару і поставте його на заставку",
 "Розкажи про свою мрію, якою ще не ділився/лася",
 "Зроби невеликий сюрприз: записка, солодощі, повідомлення",
 "Придумайте спільну традицію на кожен тиждень",
 "Додай один подарунок у свій вішліст",
 "Подивись у вішліст партнера і приховано забронюй дрібничку",
 "Станцюйте під вашу пісню на кухні",
 "Запитай: «Чим я можу допомогти тобі сьогодні?»",
 "Згадай смішний момент з вашого життя і розсмішіть одне одного",
]
def task_for(d): return TASKS[d.toordinal() % len(TASKS)]
def today(): return dt.date.today()

def ensure_user(uid, name):
    if not q("select 1 from users where id=?", uid):
        ex("insert into users(id,name,code,token) values(?,?,?,?)",
           uid, name, secrets.token_urlsafe(6), secrets.token_urlsafe(12))

def partner_id(uid):
    u = q("select couple from users where id=?", uid)[0]
    if not u["couple"]: return None
    c = q("select * from couples where id=?", u["couple"])[0]
    return c["b"] if c["a"] == uid else c["a"]

def join(uid, code):
    inv = q("select id from users where code=?", code)
    if not inv or inv[0]["id"] == uid: return None
    pid = inv[0]["id"]
    for x in (uid, pid):
        if partner_id(x): return None
    cid = ex("insert into couples(a,b,start) values(?,?,?)", pid, uid, today().isoformat())
    db.execute("update users set couple=? where id in (?,?)", (cid, uid, pid)); db.commit()
    return pid

def state(uid):
    u = q("select * from users where id=?", uid)[0]
    s = {"me": {"id": uid, "name": u["name"]}, "invite": f"https://t.me/{BOTNAME}?start={u['code']}",
         "code": u["code"], "token": u["token"], "task": task_for(today()), "today": today().isoformat()}
    pid = partner_id(uid)
    if pid:
        c = q("select * from couples where id=?", u["couple"])[0]
        s["partner"] = {"id": pid, "name": q("select name from users where id=?", pid)[0]["name"]}
        s["start"] = c["start"]
        dn = {r["user"] for r in q("select user from done where couple=? and day=?", c["id"], today().isoformat())}
        s["done"] = {"me": uid in dn, "partner": pid in dn}
        s["mine"] = [dict(r) for r in q("select id,title,link from wishes where owner=?", uid)]
        s["theirs"] = [{"id": r["id"], "title": r["title"], "link": r["link"], "reserved": r["reserved_by"] is not None,
                        "byMe": r["reserved_by"] == uid}
                       for r in q("select * from wishes where owner=?", pid)]
    return s

def check(init):
    d = dict(parse_qsl(init)); h = d.pop("hash", "")
    s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(key, s.encode(), hashlib.sha256).hexdigest(), h): return None
    return json.loads(d["user"])

async def api(r):
    b = await r.json(); u = check(b.get("init", ""))
    if not u: return web.json_response({"error": "auth"}, status=401)
    uid = u["id"]; ensure_user(uid, u.get("first_name", "Я"))
    me = q("select * from users where id=?", uid)[0]; cid = me["couple"]; a = r.match_info["a"]; pid = partner_id(uid)
    if a == "join":
        p = join(uid, b.get("code", "").strip())
        if p: await bot.send_message(p, f"💞 {me['name']} приєднався/лась до тебе!")
    elif a == "start" and cid:
        ex("update couples set start=? where id=?", dt.date.fromisoformat(b["date"]).isoformat(), cid)
    elif a == "done" and cid:
        k = (cid, today().isoformat(), uid)
        if q("select 1 from done where couple=? and day=? and user=?", *k): ex("delete from done where couple=? and day=? and user=?", *k)
        else: ex("insert into done values(?,?,?)", *k)
    elif a == "wish_add" and cid and b.get("title", "").strip():
        ex("insert into wishes(owner,title,link) values(?,?,?)", uid, b["title"][:120], b.get("link", "")[:300])
    elif a == "wish_del": ex("delete from wishes where id=? and owner=?", b["id"], uid)
    elif a == "reserve" and pid:
        w = q("select reserved_by from wishes where id=? and owner=?", b["id"], pid)
        if w and w[0]["reserved_by"] in (None, uid):
            ex("update wishes set reserved_by=? where id=?", None if w[0]["reserved_by"] else uid, b["id"])
    elif a == "unpair" and cid:
        db.execute("update users set couple=null where couple=?", (cid,)); db.commit()
    return web.json_response(state(uid))

async def widget(r):
    u = q("select * from users where token=?", r.query.get("t", ""))
    if not u or not u[0]["couple"]: return web.json_response({"error": "no couple"}, status=404)
    s = state(u[0]["id"]); days = (today() - dt.date.fromisoformat(s["start"])).days + 1
    return web.json_response({"days": days, "partner": s["partner"]["name"], "start": s["start"], "task": s["task"]})

rooms, rstate = {}, {}
async def ws(r):
    w = web.WebSocketResponse(heartbeat=25); await w.prepare(r)
    cid = None
    async for m in w:
        if m.type != WSMsgType.TEXT: continue
        d = json.loads(m.data)
        if cid is None:
            u = check(d.get("init", ""))
            if not u: break
            ensure_user(u["id"], u.get("first_name", "Я")); cid = q("select couple from users where id=?", u["id"])[0]["couple"]
            if not cid: break
            rooms.setdefault(cid, set()).add(w)
            st = rstate.get(cid)
            if st:
                t = st["t"] + (asyncio.get_event_loop().time() - st["at"] if st["playing"] else 0)
                await w.send_json({"type": "load", "url": st["url"], "t": t, "playing": st["playing"]})
            continue
        t = d.get("type"); loop = asyncio.get_event_loop().time()
        if t == "load": rstate[cid] = {"url": d["url"], "t": 0, "playing": False, "at": loop}
        elif t in ("play", "pause", "seek") and cid in rstate:
            st = rstate[cid]; st.update(t=d.get("t", 0), at=loop, playing=(t == "play") if t != "seek" else st["playing"])
        for o in rooms[cid]:
            if o is not w: await o.send_json(d)
    if cid: rooms.get(cid, set()).discard(w)
    return w

def open_kb(text="💞 Відкрити"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=BASE + "/"))]])

@dp.message(CommandStart())
async def start(m: Message, command: CommandObject):
    ensure_user(m.from_user.id, m.from_user.first_name)
    if command.args:
        p = join(m.from_user.id, command.args)
        if p:
            await bot.send_message(p, f"💞 {m.from_user.first_name} приєднався/лась до тебе!", reply_markup=open_kb())
            return await m.answer("Готово! Ви тепер пара 💞", reply_markup=open_kb())
    await m.answer("Привіт! Це ваш спільний простір для двох: лічильник днів, завдання, кіно та вішлисти.",
                   reply_markup=open_kb())

async def daily():
    while True:
        n = dt.datetime.now(); nxt = n.replace(hour=PUSH_HOUR, minute=0, second=0, microsecond=0)
        if nxt <= n: nxt += dt.timedelta(days=1)
        await asyncio.sleep((nxt - n).total_seconds())
        for c in q("select * from couples"):
            days = (today() - dt.date.fromisoformat(c["start"])).days + 1
            for uid in (c["a"], c["b"]):
                try: await bot.send_message(uid, f"💞 День {days} разом\n\nЗавдання дня: {task_for(today())}", reply_markup=open_kb("Виконати"))
                except Exception: pass

async def main():
    global BOTNAME
    BOTNAME = (await bot.get_me()).username
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="💞 Ми", web_app=WebAppInfo(url=BASE + "/")))
    app = web.Application()
    app.router.add_get("/", lambda r: web.FileResponse("webapp/index.html"))
    app.router.add_post("/api/{a}", api); app.router.add_get("/widget", widget); app.router.add_get("/ws", ws)
    run = web.AppRunner(app); await run.setup(); await web.TCPSite(run, "0.0.0.0", PORT).start()
    asyncio.create_task(daily()); await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
