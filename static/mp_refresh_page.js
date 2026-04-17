/**
 * Refresh log: add row; click-to-edit start/end; row click → detail modal; PATCH; delete rows.
 */
(function () {
  'use strict';

  function readCreateUrl(root) {
    return (root && root.getAttribute('data-create-url')) || '/api/refresh';
  }

  function apiRefreshDetailUrl(root, id) {
    var tpl = (root && root.getAttribute('data-api-refresh-detail')) || '';
    return tpl.replace(/\/\d+\/detail$/, '/' + id + '/detail');
  }

  function editTuneHref(root, tuneId) {
    var tpl = (root && root.getAttribute('data-edit-tune')) || '';
    var i = tpl.lastIndexOf('/');
    if (i < 0) return '/edit/' + tuneId;
    return tpl.slice(0, i + 1) + tuneId;
  }

  function normalizeCellValue(s) {
    return String(s || '').trim().replace('T', ' ', 1);
  }

  function formatBtnLabel(raw) {
    var s = String(raw || '').trim();
    if (!s) return '—';
    s = s.replace('T', ' ', 1);
    if (s.length >= 16 && s.charAt(10) === ' ') return s.substring(0, 16);
    if (s.length >= 10) return s.substring(0, 10);
    return s;
  }

  function syncDatetimeCell(td) {
    var inp = td.querySelector('.refresh-datetime-input');
    var btn = td.querySelector('.refresh-datetime-display');
    if (!inp || !btn) return;
    btn.textContent = formatBtnLabel(inp.value);
    var isEnd = td.classList.contains('refresh-col-datetime--end');
    btn.classList.toggle('refresh-datetime-display--empty', isEnd && !String(inp.value || '').trim());
  }

  function enterEdit(td) {
    if (!td || td.classList.contains('is-editing')) return;
    td.classList.add('is-editing');
    var inp = td.querySelector('.refresh-datetime-input');
    if (!inp) return;
    inp.removeAttribute('hidden');
    inp.focus();
    try {
      inp.select();
    } catch (e) {}
  }

  function leaveEdit(td) {
    if (!td) return;
    td.classList.remove('is-editing');
    var inp = td.querySelector('.refresh-datetime-input');
    if (inp) {
      inp.setAttribute('hidden', '');
      syncDatetimeCell(td);
    }
  }

  function rowHasChanges(tr) {
    var sa = tr.querySelector('.refresh-start-at');
    var ea = tr.querySelector('.refresh-end-at');
    if (!sa || !ea) return false;
    if (normalizeCellValue(sa.value) !== normalizeCellValue(sa.getAttribute('data-initial'))) return true;
    if (normalizeCellValue(ea.value) !== normalizeCellValue(ea.getAttribute('data-initial'))) return true;
    return false;
  }

  function buildPayload(tr) {
    var sa = tr.querySelector('.refresh-start-at');
    var ea = tr.querySelector('.refresh-end-at');
    var start = normalizeCellValue(sa && sa.value);
    var endRaw = normalizeCellValue(ea && ea.value);
    return {
      start_at: start,
      end_at: endRaw || null,
    };
  }

  function revertRow(tr) {
    var sa = tr.querySelector('.refresh-start-at');
    var ea = tr.querySelector('.refresh-end-at');
    if (!sa || !ea) return;
    sa.value = (sa.getAttribute('data-initial') || '').trim();
    var ev = (ea.getAttribute('data-initial') || '').trim();
    ea.value = ev;
    ea.classList.toggle('refresh-end-at--open', !ev);
    syncDatetimeCell(sa.closest('.refresh-col-datetime'));
    syncDatetimeCell(ea.closest('.refresh-col-datetime'));
  }

  function bindRefreshDetailModal(root) {
    var backdrop = document.getElementById('refreshDetailBackdrop');
    if (!backdrop) return;
    var closeBtn = document.getElementById('refreshDetailCloseBtn');
    var titleEl = document.getElementById('refreshDetailTitle');
    var errEl = document.getElementById('refreshDetailError');
    var contentEl = document.getElementById('refreshDetailContent');
    var loadEl = document.getElementById('refreshDetailLoading');
    var tunesEl = document.getElementById('refreshDetailTunes');
    var tunesCountEl = document.getElementById('refreshDetailTunesCount');

    function closeModal() {
      backdrop.hidden = true;
      backdrop.setAttribute('aria-hidden', 'true');
      document.removeEventListener('keydown', onDocKey);
    }

    function onDocKey(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeModal();
      }
    }

    function openModal() {
      backdrop.hidden = false;
      backdrop.setAttribute('aria-hidden', 'false');
      document.addEventListener('keydown', onDocKey);
      if (closeBtn) closeBtn.focus();
    }

    function showLoading() {
      if (errEl) {
        errEl.hidden = true;
        errEl.textContent = '';
      }
      if (contentEl) contentEl.hidden = true;
      if (loadEl) loadEl.hidden = false;
    }

    function showError(msg) {
      if (loadEl) loadEl.hidden = true;
      if (contentEl) contentEl.hidden = true;
      if (errEl) {
        errEl.textContent = msg || 'Could not load.';
        errEl.hidden = false;
      }
    }

    function renderDetail(data) {
      if (loadEl) loadEl.hidden = true;
      if (errEl) errEl.hidden = true;
      if (contentEl) contentEl.hidden = false;

      if (titleEl) titleEl.textContent = 'Refresh #' + data.refresh_number;

      var start = document.getElementById('refreshDetailStart');
      var end = document.getElementById('refreshDetailEnd');
      var days = document.getElementById('refreshDetailDays');
      var rec = document.getElementById('refreshDetailRecords');
      var uniq = document.getElementById('refreshDetailUnique');
      if (start) start.textContent = formatBtnLabel(data.start_at);
      if (end) end.textContent = data.end_at ? formatBtnLabel(data.end_at) : '— (open)';
      if (days) days.textContent = String(data.days_span);
      if (rec) rec.textContent = String(data.practice_records);
      if (uniq) uniq.textContent = String(data.unique_tune_count);

      if (tunesCountEl) tunesCountEl.textContent = '(' + (data.tunes && data.tunes.length) + ')';
      if (tunesEl) {
        tunesEl.innerHTML = '';
        if (data.tunes && data.tunes.length) {
          data.tunes.forEach(function (t) {
            var li = document.createElement('li');
            var a = document.createElement('a');
            a.href = editTuneHref(root, t.id);
            a.textContent = t.name;
            li.appendChild(a);
            tunesEl.appendChild(li);
          });
        } else {
          var empty = document.createElement('li');
          empty.className = 'refresh-detail-tunes-empty';
          empty.textContent = 'No practice records in this period.';
          tunesEl.appendChild(empty);
        }
      }
    }

    function openRefreshDetail(refreshId) {
      openModal();
      showLoading();
      fetch(apiRefreshDetailUrl(root, refreshId))
        .then(function (r) {
          return r.json().then(function (j) {
            return { ok: r.ok, j: j };
          });
        })
        .then(function (res) {
          if (!res.ok || !res.j || !res.j.ok) {
            showError((res.j && res.j.error) || 'Could not load.');
            return;
          }
          renderDetail(res.j);
        })
        .catch(function () {
          showError('Could not load.');
        });
    }

    closeBtn &&
      closeBtn.addEventListener('click', function () {
        closeModal();
      });
    backdrop.addEventListener('click', function (e) {
      if (e.target === backdrop) closeModal();
    });

    window.mpOpenRefreshDetail = openRefreshDetail;
    window.mpCloseRefreshDetail = closeModal;
  }

  function run() {
    var root = document.getElementById('refreshPage');
    var addBtn = document.getElementById('refreshLogAddBtn');
    var body = document.getElementById('refreshLogBody');
    if (!root || !addBtn || !body) return;

    bindRefreshDetailModal(root);

    var createUrl = readCreateUrl(root);

    addBtn.addEventListener('click', function () {
      addBtn.disabled = true;
      fetch(createUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      })
        .then(function (r) {
          return r.json().then(function (j) {
            return { ok: r.ok, j: j };
          });
        })
        .then(function (res) {
          if (!res.ok || !res.j || !res.j.ok) {
            if (res.j && res.j.error) console.warn(res.j.error);
            return;
          }
          window.location.reload();
        })
        .catch(function (e) {
          console.error('refresh create failed', e);
        })
        .then(function () {
          addBtn.disabled = false;
        });
    });

    body.addEventListener('click', function (e) {
      var disp = e.target.closest('.refresh-datetime-display');
      if (disp && body.contains(disp)) {
        var td = disp.closest('.refresh-col-datetime');
        if (td) enterEdit(td);
        return;
      }

      var btn = e.target.closest('.refresh-log-delete');
      if (btn && body.contains(btn)) {
        var url = btn.getAttribute('data-delete-url');
        if (!url) return;
        if (!window.confirm('Delete this refresh record?')) return;
        btn.disabled = true;
        fetch(url, { method: 'DELETE' })
          .then(function (r) {
            return r.json().then(function (j) {
              return { ok: r.ok, j: j };
            });
          })
          .then(function (res) {
            if (!res.ok || !res.j || !res.j.ok) {
              if (res.j && res.j.error) console.warn(res.j.error);
              btn.disabled = false;
              return;
            }
            window.location.reload();
          })
          .catch(function (err) {
            console.error('refresh delete failed', err);
            btn.disabled = false;
          });
        return;
      }

      if (e.target.closest('.refresh-col-datetime')) return;
      if (e.target.closest('.col-actions')) return;

      var tr = e.target.closest('tr.refresh-log-data-row');
      if (!tr || !body.contains(tr)) return;
      var rid = tr.getAttribute('data-refresh-id');
      if (!rid || !window.mpOpenRefreshDetail) return;
      window.mpOpenRefreshDetail(rid);
    });

    body.addEventListener('focusout', function (e) {
      var t = e.target;
      if (!body.contains(t) || !t.classList.contains('refresh-datetime-input')) return;
      var td = t.closest('.refresh-col-datetime');
      if (!td || !td.classList.contains('is-editing')) return;
      window.setTimeout(function () {
        if (!td.classList.contains('is-editing')) return;
        if (td.contains(document.activeElement)) return;
        leaveEdit(td);
      }, 0);
    });

    body.addEventListener('keydown', function (e) {
      var t = e.target;
      if (!body.contains(t) || !t.classList.contains('refresh-datetime-input')) return;
      if (e.key === 'Enter') {
        e.preventDefault();
        t.blur();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        t.value = (t.getAttribute('data-initial') || '').trim();
        t.blur();
      }
    });

    body.addEventListener('change', function (e) {
      var t = e.target;
      if (!body.contains(t) || !t.closest('.refresh-datetime-input')) return;

      var tr = t.closest('tr');
      if (!tr) return;
      var url = t.getAttribute('data-patch-url');
      if (!url) {
        var any = tr.querySelector('[data-patch-url]');
        url = any && any.getAttribute('data-patch-url');
      }
      if (!url) return;

      if (!rowHasChanges(tr)) return;

      var payload = buildPayload(tr);
      if (!payload.start_at) return;

      fetch(url, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
        .then(function (r) {
          return r.json().then(function (j) {
            return { ok: r.ok, j: j };
          });
        })
        .then(function (res) {
          if (!res.ok || !res.j || !res.j.ok) {
            if (res.j && res.j.error) console.warn(res.j.error);
            revertRow(tr);
            return;
          }
          window.location.reload();
        })
        .catch(function (err) {
          console.error('refresh patch failed', err);
          revertRow(tr);
        });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
