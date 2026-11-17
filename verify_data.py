"""Supplement hourly/minute audits with native-4H and quote-volume comparisons."""
import json,zipfile
import numpy as np
import pandas as pd
from download import ROOT,SYMBOLS,job,load

def main():
    out=ROOT/'results'; out.mkdir(exist_ok=True)
    records=[]; comparisons=[]; discrepancies=[]
    for symbol in SYMBOLS:
        h=load(symbol,'1h'); m=load(symbol,'1m')
        a=m.quote_volume.resample('1h').sum(); n=m.close.resample('1h').count(); a=a[n==60]
        v=h.quote_volume.reindex(a.index); bad=~np.isclose(a,v,rtol=1e-7,atol=1e-6)
        for t in a.index[bad]:
            discrepancies.append({'symbol':symbol,'time':str(t),'minute_quote':a[t],'hour_quote':v[t],
                                  'relative_difference':(a[t]-v[t])/v[t]})
        agg=h.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','quote_volume':'sum'})
        for month in ['2021-11','2026-10']:
            records.append(job((symbol,'4h','monthly',month)))
            path=ROOT/'data'/'raw'/symbol/'4h'/f'{symbol}-4h-{month}.zip'
            with zipfile.ZipFile(path) as z: d=pd.read_csv(z.open(z.namelist()[0]),header=None)
            ts=d[0].to_numpy(); d.index=pd.to_datetime(np.where(ts>1e14,ts/1000,ts),unit='ms',utc=True)
            for col,k in [('open',1),('high',2),('low',3),('close',4),('quote_volume',7)]:
                bad=~np.isclose(d[k].astype(float),agg[col].reindex(d.index),rtol=1e-7,atol=1e-6)
                comparisons.append({'symbol':symbol,'month':month,'field':col,'bars':len(d),'mismatches':int(bad.sum())})
    for name,value in [('native_4h_sample_manifest',records),('native_4h_comparison',comparisons),('quote_volume_discrepancies',discrepancies)]:
        (out/f'{name}.json').write_text(json.dumps(value,indent=2))
    print('Native 4H mismatches:',sum(x['mismatches'] for x in comparisons))
    print('Quote-volume discrepancies:',len(discrepancies))

if __name__=='__main__': main()
