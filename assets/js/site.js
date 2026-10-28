/* Расфадаль. Мир. Хроника — клиентские улучшения.
   Без JS сайт остаётся читаемым: все ходы и карты отрендерены статически. */

(function () {
  "use strict";

  var HEADER_OFFSET = 84;

  /* ---------------------------------------------------------------------- */
  /* Мобильное меню                                                          */
  /* ---------------------------------------------------------------------- */

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

  /* ---------------------------------------------------------------------- */
  /* Ходы: переключение, фильтры и поиск                                     */
  /* ---------------------------------------------------------------------- */

  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-turn-tab]"));
  var turns = Array.prototype.slice.call(document.querySelectorAll("[data-turn]"));
  var filtersBox = document.querySelector("[data-filters]");
  var filterList = document.querySelector("[data-filter-list]");
  var searchBox = document.querySelector("[data-search]");
  var searchInput = document.querySelector("[data-search-input]");
  var searchHint = document.querySelector("[data-search-hint]");

  var state = { turn: null, type: "all", query: "" };

  function normalize(value) {
    return String(value).toLowerCase().replace(/ё/g, "е");
  }

  function eachEvent(turn, callback) {
    Array.prototype.forEach.call(turn.querySelectorAll(".event"), callback);
  }

  function eventMatches(event, type, query) {
    if (type !== "all" && event.dataset.type !== type) {
      return false;
    }
    if (!query) {
      return true;
    }
    return normalize(event.textContent).indexOf(query) !== -1;
  }

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

  function render() {
    var query = normalize(state.query.trim());
    if (query) {
      applySearchView(query);
    } else {
      applyTurnView();
    }
  }

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

  function turnFromHash() {
    var match = /^#turn-(\d+)/.exec(window.location.hash);
    return match ? match[1] : null;
  }

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

  /* ---------------------------------------------------------------------- */
  /* Карты: фильтр по разделу                                                */
  /* ---------------------------------------------------------------------- */

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

  /* ---------------------------------------------------------------------- */
  /* Постройки: поиск по каталогу                                            */
  /* ---------------------------------------------------------------------- */

  var buildingSearch = document.querySelector("[data-buildings-search]");
  var buildingInput = document.querySelector("[data-buildings-input]");
  var buildingHint = document.querySelector("[data-buildings-hint]");

  if (buildingSearch && buildingInput) {
    var buildingCards = Array.prototype.slice.call(document.querySelectorAll(".building"));
    var buildingSections = Array.prototype.slice.call(
      document.querySelectorAll('section[id^="cat-"]')
    );

    buildingSearch.hidden = false;

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

  /* ---------------------------------------------------------------------- */
  /* Отступ для якорей при прокрутке                                         */
  /* ---------------------------------------------------------------------- */

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
})();
