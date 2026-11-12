'use client';
import {Area,AreaChart,CartesianGrid,ResponsiveContainer,Tooltip,XAxis,YAxis} from 'recharts';
const tomanChart=(value:number)=>Math.round(Number(value||0)/1000).toLocaleString('en-US');
export default function RevenueChart({data,ticks}:{data:{date:string;label:string;sales:number}[];ticks:string[]}) {
 return (<ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data} margin={{ left: 12, right: 24, top: 8, bottom: 8 }}>
                <defs><linearGradient id="rev" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#69a7ff" stopOpacity={0.65}/><stop offset="95%" stopColor="#69a7ff" stopOpacity={0}/></linearGradient></defs>
                <CartesianGrid stroke="rgba(148,163,184,.12)" vertical={false} />
                <XAxis dataKey="label" ticks={ticks} interval="preserveStartEnd" padding={{left:8,right:12}} minTickGap={18} tick={(props:any)=><text x={props.x} y={props.y+14} textAnchor={props.payload.value===ticks[ticks.length-1]?'end':props.payload.value===ticks[0]?'start':'middle'} fill="#aab4c8" fontSize={12}>{props.payload.value}</text>} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#aab4c8', fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={(v) => tomanChart(Number(v))} />
                <Tooltip contentStyle={{ background: '#091524', border: '1px solid rgba(145,190,253,.22)', borderRadius: 12 }} formatter={(value) => `${tomanChart(Number(value))} × 1,000 Toman`} />
                <Area type="monotone" dataKey="sales" stroke="#7db3ff" strokeWidth={3} fill="url(#rev)" dot={false} activeDot={{ r: 7 }} />
              </AreaChart>
            </ResponsiveContainer>);
}
