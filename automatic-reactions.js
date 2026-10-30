(async function () {
  const root = document.getElementById('automatic-reactions');
  if (!root) return;
  // Display convention: 1 gold pip = USD 0.01/oz. Not universal across brokers.
  const PIP_SIZE = 0.01;
  const WINDOW = '30';
  const groups = ['FOMC', 'CPI', 'PPI', 'GDP', 'PCE', 'CLAIMS'];
  function note(item) {
    const title = String(item.title || '');
    if (item.category === 'FOMC') {
      if (/minutes of the federal open market committee/i.test(title)) return 'FOMC minutes released — no new rate decision';
      const decisions = {
        '20261028': 'Rates unchanged — 3.75%–4.00%',
        '20260916': 'Rates increased 0.25 percentage points — 3.75%–4.00%',
        '20260729': 'Rates unchanged — 3.50%–3.75%'
      };
      const match = String(item.url || '').match(/monetary(\d{8})a\.htm/);
      return match && decisions[match[1]] ? decisions[match[1]] : 'FOMC rate decision — details not yet verified';
    }
    if (item.category === 'GDP') return 'US economic growth report';
    if (item.category === 'PCE') return 'Federal Reserve inflation measure';
    if (item.category === 'CLAIMS') return 'Weekly unemployment claims';
    const m = title.match(/(?:increases?|rises?|rose|up|advances?|falls?|fell|declines?|decreases?|drops?)\s+([\d.]+%)/i);
    if (m) return (item.category === 'CPI' ? 'Consumer prices' : 'Producer prices') + ' ' + (/fall|declin|decreas|drop/i.test(m[0]) ? 'fell ' : 'rose ') + m[1];
    return item.category === 'CPI' ? 'Consumer inflation report' : 'Producer inflation report';
  }
  function make(tag, cls, value) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (value !== undefined) el.textContent = value;
    return el;
  }
  async function refresh() {
    try {
      const response = await fetch('./reactions.json?t=' + Date.now(), {cache:'no-store'});
      if (!response.ok) throw new Error('Historical data unavailable');
      const data = await response.json();
      const items = Array.isArray(data.items) ? data.items : [];
      root.replaceChildren();
      const summary = make('p','muted',items.length + ' verified historical reactions. Showing the latest six per announcement type.');
      root.append(summary);
      const explanation = make('p','muted','Spike measured using first-minute close direction and highest/lowest prices in the first 5 minutes. This is not tick-level first-move data. Pip display assumes $0.01 per pip; brokers vary.');
      root.append(explanation);
      for (const category of groups) {
        const section = make('section','history-group');
        section.append(make('h3','history-heading',category + ' history'));
        const subset = items.filter(x => x.category === category).sort((a,b)=>new Date(b.release_time_utc)-new Date(a.release_time_utc));
        if (!subset.length) section.append(make('p','muted','No verified reactions yet.'));
        for (const item of subset.slice(0,6)) {
          const card = make('article','history-card');
          const date = new Date(item.release_time_utc || item.published);
          card.append(make('div','history-date',date.toLocaleDateString('en-ZA',{timeZone:'Africa/Johannesburg',day:'numeric',month:'short',year:'numeric'})));
          card.append(make('div','history-note',note(item)));
          const spike = item.spikes && item.spikes['5'];
          if (spike && Number.isFinite(spike.up_usd) && Number.isFinite(spike.down_usd)) {
            const first = spike.first_minute_direction;
            const direction = first === 'UP' ? 'rose' : first === 'DOWN' ? 'dropped' : 'was flat';
            const main = first === 'UP' ? spike.up_usd : first === 'DOWN' ? spike.down_usd : Math.max(spike.up_usd,spike.down_usd);
            const pips = Math.round(main / PIP_SIZE).toLocaleString('en-ZA');
            card.append(make('div','history-move '+(first==='UP'?'good':first==='DOWN'?'bad':''),'First minute '+direction+'; 5-min '+(first==='UP'?'up':first==='DOWN'?'down':'largest')+' spike '+pips+' pips'));
            if (spike.up_usd > 0 && spike.down_usd > 0) {
              card.append(make('div','muted','5-min range: up '+Math.round(spike.up_usd/PIP_SIZE).toLocaleString('en-ZA')+' / down '+Math.round(spike.down_usd/PIP_SIZE).toLocaleString('en-ZA')+' pips'));
            }
          } else {
            card.append(make('div','muted','Initial spike data awaiting OHLC verification'));
          }
          section.append(card);
        }
        if (subset.length>6) {
          const details=make('details','history-older');
          details.append(make('summary','', 'Show '+(subset.length-6)+' older '+category+' reactions'));
          for(const item of subset.slice(6)) {
            const row=make('p','muted');
            const d=new Date(item.release_time_utc || item.published).toLocaleDateString('en-ZA',{timeZone:'Africa/Johannesburg',day:'numeric',month:'short',year:'numeric'});
            const s=item.spikes&&item.spikes['5'];
            row.textContent=d+' — '+note(item)+' — '+(s?'First minute '+s.first_minute_direction+', 5m up '+Math.round(s.up_usd/PIP_SIZE)+' / down '+Math.round(s.down_usd/PIP_SIZE)+' pips':'Spike data pending');
            details.append(row);
          }
          section.append(details);
        }
        root.append(section);
      }
      const footer=make('p','muted','Unverified news outcomes are labelled. Spike ranges are measured price moves, not proof the announcement caused them.');
      root.append(footer);
    } catch(e) {
      root.textContent='Could not load verified historical reactions. Please refresh.';
    }
  }
  await refresh();
  setInterval(refresh,120000);
})();
