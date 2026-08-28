export type Envelope={timestamp:string;source:string;version:string;data_quality:string;last_update:string|null;data_age_seconds:number|null;stale:boolean;max_age_seconds?:number|null;data:any};
const base='/api';
export async function get(path:string):Promise<Envelope>{const response=await fetch(`${base}${path}`);if(!response.ok)throw new Error(`API ${response.status}`);return response.json()}
export async function loadDashboard(symbol:string){const paths=['/dashboard/overview',`/dashboard/market/${symbol}`,`/dashboard/mtf/${symbol}`,`/dashboard/liquidity/${symbol}`,`/dashboard/indicators/${symbol}`,`/dashboard/ai/${symbol}`,`/dashboard/strategy/${symbol}`,'/dashboard/risk','/dashboard/positions','/dashboard/performance','/dashboard/journal','/dashboard/alerts',`/dashboard/timeline/${symbol}`,'/dashboard/mt5','/dashboard/execution','/dashboard/observation'];const values=await Promise.all(paths.map(get));return Object.fromEntries(paths.map((p,i)=>[p.split('/')[2]||'overview',values[i]]))}

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

// System health is its own endpoint so a failing component is visible even when
// the observation cycle itself cannot run.
export async function loadSystemHealth():Promise<Envelope|null>{
  try{return await get('/system/health')}catch{return null}
}

// Separate from loadDashboard: '/dashboard/ai' would collide with the Phase 9
// '/dashboard/ai/{symbol}' key that loadDashboard derives from the URL segment.
export async function loadLearning():Promise<Envelope|null>{
  try{return await get('/dashboard/ai')}catch{return null}
}

// The Phase 14 forward-observation panel. Its own loader for the same reason as
// loadLearning: '/dashboard/forward' carries state loadDashboard does not key on.
export async function loadForward():Promise<Envelope|null>{
  try{return await get('/dashboard/forward')}catch{return null}
}

// The Phase 15 research panel. Its own loader, like loadLearning and loadForward.
export async function loadResearch():Promise<Envelope|null>{
  try{return await get('/dashboard/research')}catch{return null}
}

// The Phase 16 controlled DEMO execution panel. Its own loader, like loadForward:
// loadDashboard would key '/dashboard/demo-execution' as 'demo-execution' and the
// panel needs the whole envelope, including its freshness.
export async function loadDemoExecution():Promise<Envelope|null>{
  try{return await get('/dashboard/demo-execution')}catch{return null}
}

// The Phase 17 shadow/DEMO validation panel. Its own loader, like loadForward:
// loadDashboard would key '/dashboard/validation' as 'validation' and the panel
// needs the whole envelope, including its freshness.
export async function loadValidation():Promise<Envelope|null>{
  try{return await get('/dashboard/validation')}catch{return null}
}
