🧟 Полное руководство по моддингу Piu piu.io

Для тех, кто никогда не программировал. Всё по шагам: где лежат моды, как их создать, что можно менять и как не сломать игру.

---

📁 Шаг 1. Где живут моды

В той же папке, где лежит game.py, создай папку:

```
addon/
```

Внутри addon/ каждая подпапка — это один мод. Например:

```
game.py
addon/
  └── my_cool_mod/
        ├── manifest.json
        └── script/
              └── main.py
```

Важно: имена папок и файлов — только латиница, цифры и _. Без пробелов и русских букв.

---

📝 Шаг 2. Два файла = один мод

2.1. manifest.json — «паспорт» мода

Это обычный текстовый файл. Открой блокнотом и напиши:

```json
{
  "name": "Супер-мод",
  "description": "Добавляет новое оружие",
  "script": "script/main.py"
}
```

Поле Что это
name Название мода (можно по-русски)
description Что делает (видно в меню модов)
script Путь к главному файлу (обычно script/main.py)

2.2. script/main.py — код мода

Это питон-файл. Пока просто создай его пустым — мы наполним его позже.

---

⚙️ Шаг 3. Как включить мод в игре

1. Запусти игру.
2. Зайди в НАСТРОЙКИ → МОДЫ (или через меню создания сервера → кнопка «МОДЫ»).
3. Поставь галочку напротив своего мода.
4. Запусти игру.

Готово! Если код с ошибкой — мод просто не загрузится, игра продолжит работать.

---

🧠 Шаг 4. Основы: что такое «функция» и «событие»

Игра устроена так: она сама вызывает твои функции, когда что-то происходит. Тебе нужно только написать что делать.

Пример: игра говорит «зомби убит» — вызывается функция on_kill. Ты пишешь:

```python
def on_kill(host, zombie, killer_id):
    print("Зомби убит!")
```

Это всё. Ты не вызываешь on_kill — игра сделает это сама. Ты только описываешь, что должно произойти.

Правила написания функции:

```python
def имя_функции(аргументы):
    # отступ 4 пробела!
    # здесь код
    pass  # если ничего не делать
```

⚠️ Отступы — это святое. Все строки внутри def должны начинаться с 4 пробелов. Иначе — ошибка.

---

🎣 Шаг 5. Список всех «событий» (хуков)

Игра вызывает эти функции, если они есть в твоём моде. Пиши только нужные — остальные можно не писать.

Событие Когда вызывается Аргументы
on_start(host, api) Мод загружен host — мир, api — помощник
on_tick(host, now, dt) Каждый тик (20 раз/сек) now — время, dt — дельта
on_draw(host, screen) Каждый кадр screen — экран для рисования
on_event(host, event) Любое действие (клик/клавиша) event — событие pygame
on_kill(host, zombie, killer_id) Убит зомби 
on_boss_killed(host, zombie, killer_id) Убит босс 
on_wave_start(host, wave) Начало волны wave — номер
on_wave_end(host, wave) Конец волны 
on_player_join(host, player) Игрок зашёл player — словарь
on_player_death(host, player) Игрок умер 
on_player_respawn(host, player) Игрок возродился 
on_bullet_hit(host, bullet, zombie) Пуля попала 
on_laser_hit(host, player, zombie, dmg) Лазер попал 
on_melee_hit(host, player, zombie, dmg) Ближний бой 
on_zombie_spawn(host, zombie) Зомби появился 
on_crate_opened(host, player, crate) Ящик открыт 
on_item_used(host, player, item) Предмет использован 
on_weapon_bought(host, player, key) Оружие куплено 
on_build_bought(host, player, key) Постройка куплена 
on_build_destroyed(host, building) Постройка сломана 
on_victory(host) Победа 
on_game_over(host) Все погибли 
on_custom_message(host_or_client, msg) Неизвестное сообщение 

Функции-фильтры (возвращают True/False):

Функция Что делает
modify_damage(host, player, dmg, type, zombie) Верни новое число урона
modify_speed(host, player, mult) Верни новый множитель скорости
modify_coin_reward(host, zombie, coins) Верни новое число монет
modify_xp_reward(host, zombie, xp) Верни новое число опыта
filter_zombie_spawn(host, kind, wave) Верни False — зомби не появится
filter_weapon_purchase(host, player, key) Верни False — покупка отменена
filter_build_place(host, player, key, gx, gy) Верни False — постройка отменена

---

🧩 Шаг 6. Что такое host — твой мир

host — это объект мира. Через него можно читать и менять всё:

```python
host.players        # словарь {id: игрок}
host.zombies        # список зомби
host.bullets        # список пуль
host.buildings      # список построек
host.crates         # список ящиков
host.wave           # текущая волна (число)
host.wave_state     # "break" / "spawning" / "fighting"
host.game_over      # True/False
host.victory        # True/False
```

Что такое «словарь» и «список»

· Список — как очередь: [1, 2, 3]. Доступ: список[0] — первый.
· Словарь — как шкаф с ярлыками: {"hp": 100, "coins": 50}. Доступ: словарь["hp"].

Пример: игрок — это словарь

```python
player = host.players[1]   # берём игрока с id=1
print(player["hp"])        # 100
player["hp"] = 50          # меняем HP
player["coins"] += 1000    # даём 1000 монет
```

---

🎯 Шаг 7. Практика: пишем первый мод

Мод «Золотой старт» — при заходе игроку даётся 5000 монет

addon/gold_start/manifest.json:

```json
{
  "name": "Золотой старт",
  "description": "При заходе даёт 5000 монет",
  "script": "script/main.py"
}
```

addon/gold_start/script/main.py:

```python
def on_player_join(host, player):
    player["coins"] += 5000
```

Всё! Готово.

---

Мод «Все зомби в 2 раза слабее»

```python
def on_zombie_spawn(host, zombie):
    zombie["hp"] = zombie["hp"] // 2
    zombie["max_hp"] = zombie["max_hp"] // 2
```

---

Мод «Волна начинается с 10-й»

```python
def on_start(host, api):
    host.wave = 9   # следующая волна будет 10-й
```

---

Мод «Каждые 5 секунд +1 монета всем»

```python
def on_tick(host, now, dt):
    if int(now) % 5 == 0:
        for player in host.players.values():
            player["coins"] += 1
```

⚠️ on_tick вызывается 20 раз в секунду — не пихай туда тяжёлые циклы, иначе игра затормозит.

---

Мод «На экране видно HP всех зомби крупно»

```python
import pygame

def on_draw(host, screen):
    font = pygame.font.SysFont("arial", 30)
    text = font.render(f"Зомби: {len(host.zombies)}", True, (255, 0, 0))
    screen.blit(text, (20, 20))
```

---

🎨 Шаг 8. Что можно менять через api

В on_start тебе дают api — «пульт управления». Через него:

8.1. Зарегистрировать новое оружие

```python
def on_start(host, api):
    api.register_weapon(
        "super_gun",                                   # внутренний ключ (латиница)
        {"price": 1000, "label": "Супер-пушка"},       # название и цена
        {"dmg": 50, "cooldown": 0.2, "pellets": 1,     # характеристики
         "spread": 0.0, "life": 1.5, "speed": 1500},
        desc="Убивает всё за секунду."                 # описание в магазине
    )
```

После этого пушка появится в магазине за 1000 монет.

8.2. Нарисовать свою иконку оружия

```python
def on_start(host, api):
    def icon(screen, rect):
        import pygame
        pygame.draw.circle(screen, (255, 100, 100), rect.center, 20)
    
    def sprite(angle):
        import pygame, math
        surf = pygame.Surface((40, 40), pygame.SRCALPHA)
        pygame.draw.rect(surf, (200, 50, 50), (10, 18, 20, 4))
        return surf
    
    api.register_weapon_renderer("super_gun", icon_fn=icon, sprite_fn=sprite)
```

8.3. Спрятать элементы интерфейса

```python
def on_start(host, api):
    api.hide_ui("minimap", "move_joy")   # убрать миникарту и джойстик
```

Доступные имена: "aim_joy", "move_joy", "btn_auto", "btn_shop_weapons", "btn_chat_open", "hotbar", "minimap".

8.4. Свои снаряды

```python
def on_start(host, api):
    def hit_handler(host, bullet, zombie):
        zombie["hp"] -= 100
    
    api.register_ammo_type("my_bullet", lambda: create_sprite())
    api.register_ammo_hit("my_bullet", hit_handler)
```

---

🔒 Шаг 9. Что НЕЛЬЗЯ делать (и почему)

Моды работают в песочнице. Это значит, что злые моды не смогут:

· ❌ Удалить твои файлы — open() работает только на чтение и только внутри папки мода.
· ❌ Запустить exec, eval, compile — их просто нет.
· ❌ Импортировать os, sys, socket, subprocess — запрещено.
· ❌ Вылезти за пределы песочницы через __class__ / __dict__ — прокси не пустит.

Что можно:

· ✅ import math — математика.
· ✅ import random — случайности.
· ✅ import pygame — рисование (но только рисование, не события мышью!).
· ✅ open("файл.txt") — читать файлы из папки своего мода.

Если нужно что-то «своё»

Сохраняй данные в памяти (переменная модуля). Файлы писать нельзя — только читать.

```python
my_counter = 0   # это глобальная переменная мода

def on_kill(host, zombie, killer_id):
    global my_counter
    my_counter += 1
```

---

🧪 Шаг 10. Как отлаживать мод

1. Запусти игру из терминала / командной строки (не двойным кликом). Тогда увидишь ошибки:
   ```
   [mods] ошибка загрузки my_mod: ...
   ```
2. Используй print(...) внутри функций — сообщения появятся в терминале.
3. Если мод не работает — проверь отступы (4 пробела!).

---

📚 Шаг 11. Шпаргалка по объектам

Зомби (z)

```python
z["x"], z["y"]           # координаты
z["hp"], z["max_hp"]     # здоровье
z["r"]                   # радиус
z["speed"]               # скорость
z["dmg"]                 # урон
z["kind"]                # тип ("normal", "runner", "tank", ...)
z["boss"]                # True/False
z["charmed"]             # True если очарован
z["id"]                  # уникальный номер
```

Игрок (p)

```python
p["x"], p["y"]           # позиция
p["hp"], p["max_hp"]     # здоровье
p["coins"]               # монеты
p["xp"], p["level"]      # опыт и уровень
p["weapon"]              # текущее оружие
p["owned_weapons"]       # список купленных
p["inventory"]           # расходники {"apple": 3, ...}
p["color"]               # цвет (r, g, b)
p["dead"]                # True если мёртв
p["id"]                  # номер игрока
```

Пуля (b)

```python
b["x"], b["y"]           # позиция
b["vx"], b["vy"]         # скорость
b["dmg"]                 # урон
b["owner"]               # id стрелявшего
b["weapon"]              # из какого оружия
```

Постройка (b)

```python
b["x"], b["y"]           # центр
b["gx"], b["gy"]         # клетка сетки
b["hp"], b["max_hp"]     # здоровье
b["kind"]                # тип ("barricade", "turret", ...)
b["owner"]               # id владельца
```

---

🎁 Шаг 12. Полезные готовые рецепты

Дать всем игрокам бесконечный миниган

```python
def on_tick(host, now, dt):
    for p in host.players.values():
        if not p["dead"]:
            p["shoot_until"] = now + 9999
```

Убить всех зомби на карте

```python
def on_wave_start(host, wave):
    if wave == 5:
        host.zombies.clear()   # на 5-й волне всех убить
```

Двойные монеты за всё

```python
def modify_coin_reward(host, zombie, coins):
    return coins * 2
```

Свой счётчик убийств на экране

```python
kills = 0

def on_kill(host, zombie, killer_id):
    global kills
    kills += 1

def on_draw(host, screen):
    import pygame
    font = pygame.font.SysFont("arial", 40)
    t = font.render(f"Убито: {kills}", True, (255, 255, 0))
    screen.blit(t, (WIDTH // 2 - 80, 100))
```

WIDTH и HEIGHT — глобальные переменные игры (1463 и 700).

Убрать всю музыку и звуки

```python
def on_start(host, api):
    try:
        import pygame
        pygame.mixer.music.stop()
    except Exception:
        pass
```

---

💡 Шаг 13. Частые ошибки и как их исправить

Ошибка Причина Решение
SyntaxError Забыл : после def def foo(host):
IndentationError Неправильные отступы Ровно 4 пробела внутри функции
NameError: name 'x' is not defined Используешь переменную, которой нет Проверь имя или добавь global
KeyError: 'hp' Нет такого ключа в словаре Проверь, что поле существует
AttributeError: атрибут 'os' запрещён Пытаешься import os Используй только math, random, pygame
Мод не грузится Ошибка в manifest.json Проверь кавычки и запятые
PermissionError Пытаешься открыть файл вне папки мода Файлы только внутри addon/твой_мод/

---

🏁 Шаг 14. Пошаговый старт новичка

1. Создай папку addon/test_mod/script/.
2. Создай manifest.json с содержимым:
   ```json
   {"name": "Тест", "description": "Проверка", "script": "script/main.py"}
   ```
3. Создай script/main.py:
   ```python
   def on_start(host, api):
       print("Мод загружен!")
   ```
4. Запусти игру через терминал: python game.py.
5. В меню СОЛО → НАСТРОЙКИ СЕРВЕРА → МОДЫ — поставь галочку.
6. В терминале должна появиться строка Мод загружен!.

Готово — ты моддер! 🎉

---

🚀 Что дальше

· Меняй по одному параметру и смотри результат.
· Копируй готовые рецепты из шага 12.
· Смотри исходный game.py — там всё, что можно менять (имена полей).
· Не бойся ошибаться — мод с багом просто не загрузится, игра продолжит работать.

Удачи!
