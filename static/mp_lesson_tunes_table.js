/**
 * Lesson Tunes page: link folder files to tunes (pills + search dropdown per row).
 */
(function () {
  'use strict';

  function readPickerTunes() {
    var el = document.getElementById('mp-lesson-tunes-picker-json');
    if (!el) return [];
    try {
      var raw = JSON.parse(el.textContent || '[]');
      return Array.isArray(raw) ? raw : [];
    } catch (e) {
      return [];
    }
  }

  function nameDupCount(all) {
    var m = Object.create(null);
    for (var i = 0; i < all.length; i++) {
      var n = String(all[i].name || '').trim();
      m[n] = (m[n] || 0) + 1;
    }
    return m;
  }

  function closeAllPickers() {
    document.querySelectorAll('.lesson-tunes-tunes-cell.lesson-tunes-picker-open').forEach(function (cell) {
      cell.classList.remove('lesson-tunes-picker-open');
      var w = cell.querySelector('.lesson-tunes-pick-wrap');
      var menu = cell.querySelector('.lesson-tunes-pick-menu');
      var inp = cell.querySelector('.lesson-tunes-pick-input');
      if (w) w.hidden = true;
      if (menu) {
        menu.hidden = true;
        menu.innerHTML = '';
      }
      if (inp) {
        inp.value = '';
        inp.setAttribute('aria-expanded', 'false');
      }
    });
  }

  function positionMenu(menu, input) {
    if (!menu || !input || menu.hidden) return;
    var r = input.getBoundingClientRect();
    var vw = window.innerWidth || document.documentElement.clientWidth;
    var pad = 8;
    var left = Math.max(pad, r.left);
    var maxW = Math.max(r.width, vw - left - pad);
    menu.style.position = 'fixed';
    menu.style.left = left + 'px';
    menu.style.top = r.bottom + 2 + 'px';
    menu.style.minWidth = r.width + 'px';
    menu.style.maxWidth = maxW + 'px';
    menu.style.zIndex = '400';
  }

  function linkedIds(pillsEl) {
    return [].map.call(pillsEl.querySelectorAll('.lesson-tune-pill'), function (p) {
      return parseInt(p.getAttribute('data-tune-id'), 10);
    }).filter(function (x) {
      return !isNaN(x);
    });
  }

  function removeEmptyHint(pillsEl) {
    var h = pillsEl.querySelector('.lesson-tunes-empty-hint');
    if (h) h.remove();
  }

  function ensureEmptyHint(pillsEl) {
    if (pillsEl.querySelector('.lesson-tune-pill')) return;
    if (pillsEl.querySelector('.lesson-tunes-empty-hint')) return;
    var s = document.createElement('span');
    s.className = 'lesson-tunes-empty-hint';
    s.textContent = 'Click to add a tune';
    pillsEl.appendChild(s);
  }

  function createPill(tuneId, tuneName) {
    var span = document.createElement('span');
    span.className = 'lesson-tune-pill';
    span.setAttribute('data-tune-id', String(tuneId));
    var lab = document.createElement('span');
    lab.className = 'lesson-tune-pill-label';
    lab.textContent = tuneName;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'lesson-tune-pill-remove';
    btn.setAttribute('aria-label', 'Remove ' + tuneName);
    btn.innerHTML = '&times;';
    span.appendChild(lab);
    span.appendChild(btn);
    return span;
  }

  function postLink(apiUrl, filename, tuneId, remove) {
    return fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: filename,
        tune_id: tuneId,
        remove: !!remove,
      }),
    })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .catch(function (err) {
        console.error('lesson-file-tune request failed', err);
        return { ok: false, j: null };
      });
  }

  function initRow(tr, allTunes, dupNames, apiUrl) {
    var filename = tr.getAttribute('data-lesson-file');
    if (!filename) return;
    var cell = tr.querySelector('.lesson-tunes-tunes-cell');
    var pillsEl = tr.querySelector('.lesson-tunes-pills');
    var pickWrap = tr.querySelector('.lesson-tunes-pick-wrap');
    var input = tr.querySelector('.lesson-tunes-pick-input');
    var menu = tr.querySelector('.lesson-tunes-pick-menu');
    if (!cell || !pillsEl || !pickWrap || !input || !menu) return;

    var activeIdx = -1;

    function availableTunes() {
      var taken = linkedIds(pillsEl);
      return allTunes.filter(function (t) {
        return taken.indexOf(t.id) === -1;
      });
    }

    function renderMenu() {
      var q = String(input.value || '').trim().toLowerCase();
      var pool = availableTunes();
      var filtered = !q
        ? pool.slice()
        : pool.filter(function (t) {
            return String(t.name || '')
              .toLowerCase()
              .indexOf(q) !== -1;
          });
      filtered = filtered.slice(0, 12);
      menu.innerHTML = '';
      activeIdx = -1;
      filtered.forEach(function (t) {
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.className = 'lesson-tunes-pick-item';
        li.setAttribute('data-tune-id', String(t.id));
        var nm = String(t.name || '').trim() || '—';
        li.textContent = nm;
        if (dupNames[nm] > 1) {
          li.textContent = nm + ' (#' + t.id + ')';
        }
        li.addEventListener('mousedown', function (e) {
          e.preventDefault();
          pickTune(t.id, nm);
        });
        menu.appendChild(li);
      });
      var has = menu.children.length > 0;
      menu.hidden = !has;
      input.setAttribute('aria-expanded', has ? 'true' : 'false');
      if (has) positionMenu(menu, input);
    }

    function pickTune(tuneId, tuneName) {
      postLink(apiUrl, filename, tuneId, false).then(function (res) {
        if (!res.ok || !res.j || !res.j.ok) {
          if (res.j && res.j.error) console.warn(res.j.error);
          return;
        }
        removeEmptyHint(pillsEl);
        if (!res.j.duplicate) {
          pillsEl.appendChild(createPill(tuneId, tuneName));
        }
        input.value = '';
        renderMenu();
        input.focus();
      });
    }

    function openPicker() {
      closeAllPickers();
      cell.classList.add('lesson-tunes-picker-open');
      pickWrap.hidden = false;
      input.value = '';
      renderMenu();
      input.focus();
    }

    cell.addEventListener('click', function (e) {
      if (e.target.closest('a')) return;
      if (e.target.closest('.lesson-tune-pill-remove')) return;
      if (e.target.closest('.lesson-tunes-pick-wrap')) return;
      openPicker();
    });

    pillsEl.addEventListener('click', function (e) {
      var rm = e.target.closest('.lesson-tune-pill-remove');
      if (!rm && e.target.closest('.lesson-tune-pill')) {
        e.stopPropagation();
        return;
      }
      if (!rm) return;
      e.preventDefault();
      e.stopPropagation();
      var pill = rm.closest('.lesson-tune-pill');
      if (!pill) return;
      var tid = parseInt(pill.getAttribute('data-tune-id'), 10);
      if (isNaN(tid)) return;
      postLink(apiUrl, filename, tid, true).then(function (res) {
        if (!res.ok || !res.j || !res.j.ok) {
          if (res.j && res.j.error) console.warn(res.j.error);
          return;
        }
        pill.remove();
        ensureEmptyHint(pillsEl);
      });
    });

    input.addEventListener('input', function () {
      renderMenu();
    });

    input.addEventListener('focus', function () {
      if (input._mpBlurTimer) {
        clearTimeout(input._mpBlurTimer);
        input._mpBlurTimer = null;
      }
      renderMenu();
    });

    input.addEventListener('keydown', function (e) {
      var opts = menu.querySelectorAll('.lesson-tunes-pick-item');
      if (e.key === 'Escape') {
        e.preventDefault();
        closeAllPickers();
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (!menu.hidden && opts.length) {
          activeIdx = activeIdx < 0 ? 0 : Math.min(activeIdx + 1, opts.length - 1);
          for (var i = 0; i < opts.length; i++) {
            opts[i].classList.toggle('lesson-tunes-pick-active', i === activeIdx);
          }
        }
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (!menu.hidden && opts.length) {
          activeIdx = activeIdx <= 0 ? -1 : activeIdx - 1;
          for (var j = 0; j < opts.length; j++) {
            opts[j].classList.toggle('lesson-tunes-pick-active', j === activeIdx);
          }
        }
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        if (!menu.hidden && activeIdx >= 0 && opts[activeIdx]) {
          var id = parseInt(opts[activeIdx].getAttribute('data-tune-id'), 10);
          var label = opts[activeIdx].textContent || '';
          if (label.indexOf(' (#') !== -1) {
            label = label.replace(/\s*\(#\d+\)\s*$/, '');
          }
          if (!isNaN(id)) pickTune(id, label);
        }
      }
    });

    input.addEventListener('blur', function () {
      if (input._mpBlurTimer) clearTimeout(input._mpBlurTimer);
      input._mpBlurTimer = setTimeout(function () {
        input._mpBlurTimer = null;
        if (document.activeElement === input) return;
        if (cell.contains(document.activeElement)) return;
        cell.classList.remove('lesson-tunes-picker-open');
        pickWrap.hidden = true;
        menu.hidden = true;
        menu.innerHTML = '';
      }, 120);
    });
  }

  function run() {
    var table = document.getElementById('lessonTunesTable');
    if (!table) return;
    var apiUrl = table.getAttribute('data-lesson-link-api') || '/api/lesson-file-tune';
    var allTunes = readPickerTunes();
    var dupNames = nameDupCount(allTunes);
    [].forEach.call(table.querySelectorAll('tbody tr[data-lesson-file]'), function (tr) {
      initRow(tr, allTunes, dupNames, apiUrl);
    });

    document.addEventListener(
      'mousedown',
      function (e) {
        if (e.target.closest('.lesson-tunes-tunes-cell')) return;
        closeAllPickers();
      },
      true
    );

    window.addEventListener('resize', closeAllPickers);
    window.addEventListener(
      'scroll',
      function () {
        document.querySelectorAll('.lesson-tunes-tunes-cell.lesson-tunes-picker-open').forEach(function (cell) {
          var menu = cell.querySelector('.lesson-tunes-pick-menu');
          var input = cell.querySelector('.lesson-tunes-pick-input');
          if (menu && input && !menu.hidden) positionMenu(menu, input);
        });
      },
      true
    );
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
