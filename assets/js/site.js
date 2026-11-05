/* ==== MODULE CONTRACT: site-js ====
 * PURPOSE:   Улучшать интерфейс прогрессивно — меню, переключение ходов, поиск и фильтры, — не мешая чтению сайта без JavaScript.
 * SCOPE:     мобильное меню, вкладки и hash-навигация ходов, фильтры событий по типу, поиск по хронике, фильтр карт, поиск по постройкам, плавная прокрутка к якорям.
 * NON-GOALS: Не рендерить контент, не хранить данные, не заменять сборку страниц, не тянуть зависимости и сборщики.
 * INVARIANTS:без JS сайт остаётся читаемым — все ходы и карты отрендерены статически; улучшения включаются только при наличии data-хуков в разметке; выключенное улучшение не ломает остальные.
 * DEPENDS:   templates:HtmlHooks, site-css:Selectors
 * EXPOSES:   site.js
 * ERRORS:    нет — ошибки не выбрасываются, улучшения молча деградируют
 * TESTS:     T-SITE-001, T-SITE-002, T-SITE-003, T-SITE-004
 * ==== END MODULE CONTRACT: site-js ==== */

(function () {
  "use strict";

  var HEADER_OFFSET = 84;

  /* PURPOSE:   Нормализовать текст для поиска, убирая различия регистра и «ё»/«е».
   * INPUTS:    value — строка или значение с toString; может быть пустым.
   * OUTPUTS:   строка в нижнем регистре, «ё» заменена на «е».
   * ERRORS:    нет — нестроковый вход приводится к строке.
   * KEYWORDS:  [Search, Normalize, Text, Eyo]
   * TESTS:     [T-SITE-002] */
  function normalize(value) {
    return String(value).toLowerCase().replace(/ё/g, "е");
  }

  // START_BLOCK_NAV_MENU: Открытие и закрытие мобильного меню с aria-состоянием. #KEYWORDS: Menu,Toggle,Aria,Mobile
  var navToggle = document.querySelector(".nav-toggle");
  var mainMenu = document.getElementById("mainmenu");

  if (navToggle && mainMenu) {
    navToggle.addEventListener("click", function () {
      var isOpen = mainMenu.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", String(isOpen));
    });

    mainMenu.addEventListener("click", function (event) {
      if (event.target.closest("a") && mainMenu.classList.contains("is-open")) {
        mainMenu.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      }
    });
  }
  // END_BLOCK_NAV_MENU

  // START_BLOCK_TURN_TABS: Состояние ходов, подсветка активной вкладки и прокрутка к ходу. #KEYWORDS: Turn,Tabs,Hash,Scroll
  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-turn-tab]"));
  var turns = Array.prototype.slice.call(document.querySelectorAll("[data-turn]"));
  var filtersBox = document.querySelector("[data-filters]");
  var filterList = document.querySelector("[data-filter-list]");
  var searchBox = document.querySelector("[data-search]");
  var searchInput = document.querySelector("[data-search-input]");
  var searchHint = document.querySelector("[data-search-hint]");

  var state = { turn: null, type: "all", query: "" };

  /* PURPOSE:   Прокрутить страницу к выбранному ходу с учётом высоты шапки.
   * INPUTS:    number — номер хода; ход ищется среди [data-turn].
   * OUTPUTS:   нет — побочный эффект window.scrollTo.
   * ERRORS:    нет — неизвестный номер молча игнорируется.
   * KEYWORDS:  [Scroll, Turn, HeaderOffset, Anchor]
   * TESTS:     [T-SITE-002] */
  function scrollToTurn(number) {
    var turn = turns.find(function (item) {
      return item.dataset.turn === String(number);
    });
    if (!turn) {
      return;
    }
    var top = turn.getBoundingClientRect().top + window.pageYOffset - HEADER_OFFSET;
    window.scrollTo({ top: top, behavior: "smooth" });
  }

  /* PURPOSE:   Подсветить вкладку активного хода и выставить aria-current.
   * INPUTS:    activeNumber — номер хода, который нужно считать активным.
   * OUTPUTS:   нет — меняет классы is-active и атрибут aria-current вкладок.
   * ERRORS:    нет — при отсутствии совпадений все вкладки остаются неактивными.
   * KEYWORDS:  [Tabs, Active, AriaCurrent, Turn]
   * TESTS:     [T-SITE-002] */
  function updateTabs(activeNumber) {
    tabs.forEach(function (tab) {
      var isActive = tab.dataset.turnTab === String(activeNumber);
      tab.classList.toggle("is-active", isActive);
      if (isActive) {
        tab.setAttribute("aria-current", "true");
      } else {
        tab.removeAttribute("aria-current");
      }
    });
  }
  // END_BLOCK_TURN_TABS

  // START_BLOCK_TURN_FILTERS: Фильтр событий активного хода по типу и пересчёт счётчиков. #KEYWORDS: Filter,Type,Chips,Counters
  /* PURPOSE:   Пройти по всем событиям хода, вызывая обработчик для каждого.
   * INPUTS:    turn — элемент хода; callback — функция обработки события.
   * OUTPUTS:   нет — побочный эффект вызовов callback.
   * ERRORS:    нет — отсутствие событий даёт ноль вызовов.
   * KEYWORDS:  [Events, Iterate, Callback, Turn]
   * TESTS:     [T-SITE-002] */
  function eachEvent(turn, callback) {
    Array.prototype.forEach.call(turn.querySelectorAll(".event"), callback);
  }

  /* PURPOSE:   Проверить, подходит ли событие под текущий тип и поисковый запрос.
   * INPUTS:    event — элемент события; type — тип события или «all»; query — уже нормализованный запрос.
   * OUTPUTS:   boolean — true, если событие видимо при заданных условиях.
   * ERRORS:    нет — пустой запрос считается совпадением.
   * KEYWORDS:  [Filter, Type, Query, Match]
   * TESTS:     [T-SITE-002] */
  function eventMatches(event, type, query) {
    if (type !== "all" && event.dataset.type !== type) {
      return false;
    }
    if (!query) {
      return true;
    }
    return normalize(event.textContent).indexOf(query) !== -1;
  }

  /* PURPOSE:   Собрать кнопку-чип фильтра с подписью и счётчиком событий.
   * INPUTS:    value — значение типа; label — подпись; count — число событий.
   * OUTPUTS:   HTMLElement — готовая кнопка .chip[data-filter].
   * ERRORS:    нет.
   * KEYWORDS:  [Chip, Filter, Button, Count]
   * TESTS:     [T-SITE-002, T-SITE-003] */
  function makeChip(value, label, count) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.dataset.filter = value;

    button.appendChild(document.createTextNode(label));

    var counter = document.createElement("span");
    counter.className = "chip__count";
    counter.textContent = String(count);
    button.appendChild(counter);

    return button;
  }

  /* PURPOSE:   Построить список чипов по типам событий активного хода и показать панель фильтров.
   * INPUTS:    turn — элемент активного хода.
   * OUTPUTS:   нет — перерисовывает [data-filter-list] и снимает hidden с [data-filters].
   * ERRORS:    нет — без панели фильтров выходит молча.
   * KEYWORDS:  [Chips, Filter, Counts, Turn, Panel]
   * TESTS:     [T-SITE-002, T-SITE-004] */
  function buildChips(turn) {
    if (!filtersBox || !filterList) {
      return;
    }

    var counts = {};
    var labels = {};
    var total = 0;

    eachEvent(turn, function (event) {
      var type = event.dataset.type;
      counts[type] = (counts[type] || 0) + 1;
      total += 1;
      if (!labels[type]) {
        var badge = event.querySelector(".badge");
        labels[type] = badge ? badge.textContent.trim() : type;
      }
    });

    if (state.type !== "all" && !counts[state.type]) {
      state.type = "all";
    }

    filterList.textContent = "";
    filterList.appendChild(makeChip("all", "Все", total));
    Object.keys(counts).forEach(function (type) {
      filterList.appendChild(makeChip(type, labels[type], counts[type]));
    });

    Array.prototype.forEach.call(filterList.querySelectorAll(".chip"), function (chip) {
      chip.classList.toggle("is-active", chip.dataset.filter === state.type);
    });

    filtersBox.hidden = false;
  }
  // END_BLOCK_TURN_FILTERS

  // START_BLOCK_TURN_SEARCH: Поиск по всей хронике с подсчётом совпадений по ходам. #KEYWORDS: Search,Query,Hint,Turns
  /* PURPOSE:   Показать только совпавшие с запросом события и посчитать совпадения по ходам.
   * INPUTS:    query — нормализованный поисковый запрос; не пустой.
   * OUTPUTS:   нет — прячет неподходящие ходы и события, обновляет [data-search-hint].
   * ERRORS:    нет — без совпадений выводит «Ничего не найдено».
   * KEYWORDS:  [Search, Filter, Hint, Turn, Count]
   * TESTS:     [T-SITE-002, T-SITE-004] */
  function applySearchView(query) {
    var found = 0;
    var turnsWithMatches = 0;

    turns.forEach(function (turn) {
      turn.hidden = false;
      turn.classList.remove("is-hidden");

      var visible = 0;
      eachEvent(turn, function (event) {
        var match = eventMatches(event, state.type, query);
        event.classList.toggle("is-filtered", !match);
        if (match) {
          visible += 1;
        }
      });

      turn.hidden = visible === 0;
      if (visible > 0) {
        found += visible;
        turnsWithMatches += 1;
      }
    });

    tabs.forEach(function (tab) {
      tab.classList.remove("is-active");
      tab.removeAttribute("aria-current");
    });

    if (filtersBox) {
      filtersBox.hidden = true;
    }
    if (searchHint) {
      searchHint.textContent = found
        ? "Совпадений: " + found + " · ходов: " + turnsWithMatches
        : "Ничего не найдено";
    }
  }
  // END_BLOCK_TURN_SEARCH

  // START_BLOCK_TURN_VIEW: Переключение вида ходов — активный ход, поиск и hash-навигация. #KEYWORDS: Turn,View,Render,Activate,Hash
  /* PURPOSE:   Показать только активный ход и применить фильтр по типу событий.
   * INPUTS:    нет — читает state.turn и state.type.
   * OUTPUTS:   нет — прячет остальные ходы, перестраивает чипы и подсвечивает вкладку.
   * ERRORS:    нет.
   * KEYWORDS:  [Turn, View, Active, Chips, Tabs]
   * TESTS:     [T-SITE-002, T-SITE-004] */
  function applyTurnView() {
    turns.forEach(function (turn) {
      turn.hidden = false;
      var active = turn.dataset.turn === String(state.turn);
      turn.classList.toggle("is-hidden", !active);

      if (active) {
        eachEvent(turn, function (event) {
          event.classList.toggle("is-filtered", !eventMatches(event, state.type, ""));
        });
        buildChips(turn);
      }
    });

    if (filtersBox) {
      filtersBox.hidden = false;
    }
    if (searchHint) {
      searchHint.textContent = "";
    }
    updateTabs(state.turn);
  }

  /* PURPOSE:   Выбрать представление хроники: поиск при непустом запросе, иначе показ одного хода.
   * INPUTS:    нет — читает state.query.
   * OUTPUTS:   нет — делегирует applySearchView или applyTurnView.
   * ERRORS:    нет.
   * KEYWORDS:  [Render, Search, Turn, Dispatch]
   * TESTS:     [T-SITE-002] */
  function render() {
    var query = normalize(state.query.trim());
    if (query) {
      applySearchView(query);
    } else {
      applyTurnView();
    }
  }

  /* PURPOSE:   Активировать ход: сбросить фильтр и поиск, обновить вид, при необходимости hash и прокрутку.
   * INPUTS:    number — номер хода; options.hash — заменить hash; options.scroll — прокрутить к ходу.
   * OUTPUTS:   нет — меняет state и, возможно, адрес страницы.
   * ERRORS:    нет — без history.replaceState hash не меняется.
   * KEYWORDS:  [Activate, Turn, Hash, Scroll, State]
   * TESTS:     [T-SITE-002, T-SITE-003] */
  function activateTurn(number, options) {
    var settings = options || {};
    state.turn = String(number);
    state.type = "all";
    state.query = "";
    if (searchInput) {
      searchInput.value = "";
    }

    render();

    if (settings.hash && window.history.replaceState) {
      window.history.replaceState(null, "", "#turn-" + number);
    }
    if (settings.scroll) {
      scrollToTurn(number);
    }
  }

  /* PURPOSE:   Извлечь номер хода из адресного hash вида #turn-N.
   * INPUTS:    нет — читает window.location.hash.
   * OUTPUTS:   string | null — номер хода или null, если hash не про ход.
   * ERRORS:    нет.
   * KEYWORDS:  [Hash, Turn, Parse, Navigation]
   * TESTS:     [T-SITE-002] */
  function turnFromHash() {
    var match = /^#turn-(\d+)/.exec(window.location.hash);
    return match ? match[1] : null;
  }
  // END_BLOCK_TURN_VIEW

  // START_BLOCK_TURN_WIRING: Привязка обработчиков к разметке ходов и стартовое состояние. #KEYWORDS: Wiring,Listeners,Hash,Initial
  if (tabs.length && turns.length) {
    if (searchBox) {
      searchBox.hidden = false;
    }

    if (searchInput) {
      searchInput.addEventListener("input", function () {
        state.query = searchInput.value;
        if (state.query.trim()) {
          state.type = "all";
        }
        render();
      });

      searchInput.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
          searchInput.value = "";
          state.query = "";
          state.type = "all";
          render();
        }
      });
    }

    if (filterList) {
      filterList.addEventListener("click", function (event) {
        var chip = event.target.closest(".chip");
        if (!chip) {
          return;
        }
        state.type = chip.dataset.filter;
        render();
      });
    }

    document.addEventListener("click", function (event) {
      var link = event.target.closest('a[href^="#turn-"]');
      if (!link) {
        return;
      }
      event.preventDefault();
      activateTurn(link.getAttribute("href").slice("#turn-".length), {
        hash: true,
        scroll: true
      });
    });

    window.addEventListener("hashchange", function () {
      var number = turnFromHash();
      if (number) {
        activateTurn(number, {});
      }
    });

    var initial = turnFromHash();
    if (initial && tabs.some(function (tab) { return tab.dataset.turnTab === initial; })) {
      activateTurn(initial, { scroll: true });
    } else {
      activateTurn(turns[turns.length - 1].dataset.turn, {});
    }
  }
  // END_BLOCK_TURN_WIRING

  // START_BLOCK_MAPS_FILTER: Фильтр карт по разделу каталога. #KEYWORDS: Maps,Filter,Category,Figures
  var mapButtons = Array.prototype.slice.call(document.querySelectorAll("[data-map-filter]"));
  var mapFigures = Array.prototype.slice.call(document.querySelectorAll("[data-category]"));

  if (mapButtons.length && mapFigures.length) {
    mapButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        var value = button.dataset.mapFilter;
        mapButtons.forEach(function (item) {
          item.classList.toggle("is-active", item === button);
        });
        mapFigures.forEach(function (figure) {
          figure.hidden = value !== "all" && figure.dataset.category !== value;
        });
      });
    });
  }
  // END_BLOCK_MAPS_FILTER

  // START_BLOCK_BUILDINGS_SEARCH: Поиск по каталогу построек и скрытие пустых разделов. #KEYWORDS: Buildings,Search,Catalog,Sections
  var buildingSearch = document.querySelector("[data-buildings-search]");
  var buildingInput = document.querySelector("[data-buildings-input]");
  var buildingHint = document.querySelector("[data-buildings-hint]");

  if (buildingSearch && buildingInput) {
    var buildingCards = Array.prototype.slice.call(document.querySelectorAll(".building"));
    var buildingSections = Array.prototype.slice.call(
      document.querySelectorAll('section[id^="cat-"]')
    );

    buildingSearch.hidden = false;

    /* PURPOSE:   Отфильтровать карточки построек по запросу и спрятать опустевшие разделы.
     * INPUTS:    нет — читает значение [data-buildings-input].
     * OUTPUTS:   нет — меняет hidden у карточек и разделов, обновляет [data-buildings-hint].
     * ERRORS:    нет — пустой запрос показывает всё.
     * KEYWORDS:  [Buildings, Filter, Sections, Hint, Search]
     * TESTS:     [T-SITE-002, T-SITE-004] */
    function filterBuildings() {
      var query = normalize(buildingInput.value.trim());
      var found = 0;

      buildingCards.forEach(function (card) {
        var match = !query || normalize(card.textContent).indexOf(query) !== -1;
        card.hidden = !match;
        if (match) {
          found += 1;
        }
      });

      buildingSections.forEach(function (section) {
        var visible = section.querySelectorAll(".building:not([hidden])").length;
        section.hidden = query !== "" && visible === 0;
      });

      if (buildingHint) {
        if (!query) {
          buildingHint.textContent = "";
        } else if (found) {
          buildingHint.textContent = "Найдено построек: " + found;
        } else {
          buildingHint.textContent = "Ничего не найдено";
        }
      }
    }

    buildingInput.addEventListener("input", filterBuildings);
    buildingInput.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        buildingInput.value = "";
        filterBuildings();
      }
    });
  }
  // END_BLOCK_BUILDINGS_SEARCH

  // START_BLOCK_SCROLL_OFFSET: Плавная прокрутка к якорям с поправкой на высоту шапки. #KEYWORDS: Anchor,Scroll,Hash,HeaderOffset
  document.addEventListener("click", function (event) {
    var link = event.target.closest('a[href^="#"]');
    if (!link) {
      return;
    }
    var id = link.getAttribute("href").slice(1);
    if (!id || /^turn-\d+$/.test(id)) {
      return;
    }
    var target = document.getElementById(id);
    if (target) {
      event.preventDefault();
      window.scrollTo({
        top: target.getBoundingClientRect().top + window.pageYOffset - HEADER_OFFSET,
        behavior: "smooth"
      });
      if (window.history.pushState) {
        window.history.pushState(null, "", "#" + id);
      }
    }
  });
  // END_BLOCK_SCROLL_OFFSET
})();
