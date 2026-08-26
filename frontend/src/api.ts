export type Envelope={timestamp:string;source:string;version:string;data_quality:string;last_update:string|null;data_age_seconds:number|null;stale:boolean;max_age_seconds?:number|null;data:any};
const base='/api';
export async function get(path:string):Promise<Envelope>{const response=await fetch(`${base}${path}`);if(!response.ok)throw new Error(`API ${response.status}`);return response.json()}
export async function loadDashboard(symbol:string){const paths=['/dashboard/overview',`/dashboard/market/${symbol}`,`/dashboard/mtf/${symbol}`,`/dashboard/liquidity/${symbol}`,`/dashboard/indicators/${symbol}`,`/dashboard/ai/${symbol}`,`/dashboard/strategy/${symbol}`,'/dashboard/risk','/dashboard/positions','/dashboard/performance','/dashboard/journal','/dashboard/alerts',`/dashboard/timeline/${symbol}`,'/dashboard/mt5','/dashboard/execution'];const values=await Promise.all(paths.map(get));return Object.fromEntries(paths.map((p,i)=>[p.split('/')[2]||'overview',values[i]]))}

// The equity curve is served by the paper API rather than a dashboard envelope.
export async function loadEquity():Promise<{timestamp:string;equity:number;drawdown:number}[]>{
  const response=await fetch(`${base}/paper/equity`);
  if(!response.ok)throw new Error(`API ${response.status}`);
  const body=await response.json();
  return Array.isArray(body?.items)?body.items:[];
}

// MT5 multi-timeframe lives on its own path so it does not collide with the
// '/dashboard/mt5' key that loadDashboard derives from the URL segment.
export async function loadMT5Timeframes(symbol:string):Promise<Envelope|null>{
  try{return await get(`/dashboard/mt5/mtf/${symbol}`)}catch{return null}
}
