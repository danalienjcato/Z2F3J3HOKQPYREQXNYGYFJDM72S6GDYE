(async function(){
const root=document.getElementById('sp-reactions');if(!root)return;
async function refresh(){
try{
 const response=await fetch('./sp500-reactions.json?t='+Date.now(),{cache:'no-store'});
 if(!response.ok)throw Error('S&P 500 historical collector has not published data');
 const data=await response.json();
 const items=Array.isArray(data.items)?data.items:[];
 root.replaceChildren();
 const status=document.createElement('p');status.className='muted';status.textContent=items.length+' S&P 500 historical reactions available. Source: '+(data.method||'not specified');root.append(status);
 for(const category of ['FOMC','CPI','PPI','GDP','PCE','CLAIMS']){
  const section=document.createElement('section');section.className='history-group';
  const h=document.createElement('h3');h.className='history-heading';h.textContent=category+' history';section.append(h);
  const selected=items.filter(x=>x.category===category).sort((a,b)=>Date.parse(b.release_time_utc)-Date.parse(a.release_time_utc));
  if(!selected.length){const p=document.createElement('p');p.className='muted';p.textContent='Awaiting verified S&P 500 price reactions.';section.append(p);}
  for(const item of selected.slice(0,6)){
   const card=document.createElement('article');card.className='history-card';
   const d=document.createElement('div');d.className='history-date';d.textContent=new Date(item.release_time_utc).toLocaleDateString('en-ZA',{timeZone:'Africa/Johannesburg'});card.append(d);
   const n=document.createElement('div');n.className='history-note';n.textContent=item.title||category;card.append(n);
   const p=document.createElement('div');p.className='history-move';
   const spike=item.spikes&&item.spikes['5'];
   if(spike&&Number.isFinite(spike.up_points)&&Number.isFinite(spike.down_points)){p.textContent='First minute '+spike.first_minute_direction+'; 5-minute high +'+spike.up_points.toFixed(2)+' / low -'+spike.down_points.toFixed(2)+' index points';p.className+=' '+(spike.first_minute_direction==='UP'?'good':spike.first_minute_direction==='DOWN'?'bad':'');}
   else p.textContent='Verified S&P 500 price movement pending';
   card.append(p);section.append(card);
  }
  root.append(section);
 }
}catch(e){root.textContent='S&P 500 historical reactions are not yet connected. No S&P 500 price movements have been verified or substituted with Gold data.';}
}
await refresh();setInterval(refresh,120000);
})();