'use client';

import React, { useState, useEffect, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams, useRouter } from 'next/navigation';

const IconTrendingUp = () => <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-500"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>;
const IconLaw = () => <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-blue-400"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>;
const IconActivity = () => <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-orange-400"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>;

function SearchInterface() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [signals, setSignals] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [ticker, setTicker] = useState("NVDA");

  useEffect(() => {
    const t = searchParams.get('ticker') || "NVDA";
    setTicker(t);
    fetchSignals(t);
  }, [searchParams]);

  const fetchSignals = (searchTicker: string) => {
    setLoading(true);
    fetch(`https://alpha-backend-n90b.onrender.com/api/signals?ticker=${searchTicker}`)
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) setSignals(data);
        else setSignals([]);
        setLoading(false);
      })
      .catch(() => { setSignals([]); setLoading(false); });
  };

  const handleSearch = () => { if (ticker.trim()) router.push(`/?ticker=${ticker}`); };

  return (
    <>
      <header className="bg-white py-5 px-4 text-center border-b border-slate-200">
        <div className="max-w-4xl mx-auto space-y-3">
          <h1 className="text-2xl font-extrabold text-slate-900">See the Bills. <span className="text-blue-600">Trade the Policy.</span></h1>
          <div className="flex justify-center gap-2 pt-2 px-2">
             <input type="text" value={ticker} onChange={(e) => setTicker(e.target.value)} onKeyDown={(e) => e.key==='Enter' && handleSearch()} placeholder="Ticker..." className="w-48 px-3 py-1.5 border border-slate-300 rounded text-slate-900" />
             <button onClick={handleSearch} className="px-4 py-1.5 bg-slate-900 text-white font-bold rounded">Search</button>
          </div>
        </div>
      </header>
      <section className="bg-slate-900 text-white py-6 px-4">
        <div className="max-w-7xl mx-auto">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[900px]">
              <thead>
                <tr className="text-[9px] uppercase text-slate-500 font-semibold border-b border-slate-800">
                  <th className="pb-3 pl-4">Ticker</th><th className="pb-3">Price</th>
                  <th className="pb-3">Congress</th><th className="pb-3">Bill ID</th>
                  <th className="pb-3">Risk Level</th>
                  <th className="pb-3">Targets (1W)</th>
                  <th className="pb-3 text-right pr-4">Conviction</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 text-xs">
                {loading && <tr><td colSpan={7} className="py-8 text-center text-slate-400 animate-pulse">Running Pro Framework Analysis...</td></tr>}
                {!loading && signals.map((s, i) => (
                  <tr key={i} className="hover:bg-slate-800/50">
                    <td className="py-4 pl-4 font-bold text-sm">
                        <a href={`https://finance.yahoo.com/quote/${s.ticker}`} target="_blank" className="hover:text-blue-400 underline">{s.ticker}</a>
                        <div className="text-[9px] text-slate-500 font-normal mt-0.5">{s.volatility_regime}</div>
                    </td>
                    <td className="py-4 text-emerald-400 font-mono font-bold">{s.price}</td>
                    <td className="py-4 text-purple-400">{s.congress_activity}</td>
                    <td className="py-4"><span className="bg-blue-500/20 text-blue-300 px-2 py-1 rounded text-[10px]">{s.bill_id}</span></td>
                    
                    {/* RISK & SKEW */}
                    <td className="py-4">
                        <div className={`flex items-center gap-1 ${s.risk_level === "High" ? "text-red-400" : "text-emerald-400"}`}>
                            <IconActivity /> {s.risk_level}
                        </div>
                        <div className="text-[9px] text-slate-500 mt-1">{s.skew}</div>
                    </td>

                    {/* TARGETS */}
                    <td className="py-4 font-mono text-slate-300">
                        {s.targets}
                    </td>

                    <td className="py-4 text-right pr-4"><span className={`px-2 py-1 rounded-full border text-[10px] font-bold ${s.sentiment==='Bullish'?'text-emerald-400 border-emerald-400/20':'text-slate-400 border-slate-400/20'}`}>{s.sentiment}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </>
  );
}

export default function AlphaInsiderHome() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 font-sans">
      <nav className="bg-white border-b border-slate-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 h-12 flex items-center justify-between">
          <div className="font-bold text-slate-900">AlphaInsider</div>
          <div className="flex gap-3 text-xs font-bold uppercase">
             <Link href="/analysis" className="text-emerald-600">Top Picks</Link>
             <Link href="/paper-trade" className="text-purple-600">Paper Trade</Link>
             <Link href="/legislation" className="text-slate-600">Legislation</Link>
          </div>
        </div>
      </nav>
      <Suspense fallback={<div>Loading...</div>}><SearchInterface /></Suspense>
    </div>
  );
}