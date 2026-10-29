(async function () {
  const root = document.getElementById('automatic-reactions');
  if (!root) return;

  async function refresh() {
    try {
      const response = await fetch('./reactions.json?t=' + Date.now(), { cache: 'no-store' });
      if (!response.ok) throw new Error('Historical data not yet published');
      const data = await response.json();
      const items = Array.isArray(data.items) ? data.items : [];
      root.replaceChildren();

      const summary = document.createElement('p');
      summary.className = 'muted';
      const updated = data.updated_at
        ? new Date(data.updated_at).toLocaleString('en-ZA', {
            timeZone: 'Africa/Johannesburg', dateStyle: 'medium', timeStyle: 'short'
          }) + ' SAST'
        : 'unknown';
      summary.textContent = items.length + ' historical reactions calculated. Last checked: ' + updated + '.';
      root.append(summary);

      if (!items.length) {
        const message = document.createElement('p');
        message.textContent = 'Historical price collection is running. No valid matching price records have been published yet.';
        root.append(message);
      }

      for (const item of items.slice(0, 45)) {
        const card = document.createElement('article');
        card.className = 'item';
        const heading = document.createElement('h3');
        heading.textContent = item.category + ' — ' + item.title;

        const meta = document.createElement('p');
        meta.className = 'muted';
        const release = new Date(item.release_time_utc || item.published);
        const releaseText = release.toLocaleString('en-ZA', {
          timeZone: 'Africa/Johannesburg', dateStyle: 'medium', timeStyle: 'short'
        });
        meta.textContent = releaseText + ' SAST release • Baseline: ' +
          Number(item.baseline).toFixed(3) + ' USD/oz';

        const moves = document.createElement('p');
        moves.className = 'muted';
        moves.textContent = [1, 5, 15, 30, 60].map(function (minutes) {
          const value = item.moves && item.moves[String(minutes)];
          return minutes + 'm: ' + (value == null
            ? 'no data'
            : (Number(value) >= 0 ? '+' : '') + Number(value).toFixed(3));
        }).join(' | ') + ' USD/oz';

        card.append(heading, meta, moves);
        root.append(card);
      }

      const errors = Object.entries(data.checks || {}).filter(function (entry) {
        return /Error|timed out|unavailable/i.test(String(entry[1]));
      });
      if (errors.length) {
        const note = document.createElement('p');
        note.className = 'muted';
        note.textContent = 'Still awaiting price data for: ' +
          errors.map(function (entry) { return entry[0]; }).join(', ') +
          '. Automatic retries are enabled.';
        root.append(note);
      }
    } catch (error) {
      root.textContent = 'Historical price results could not be loaded. Please refresh later.';
    }
  }

  await refresh();
  setInterval(refresh, 120000);
})();
