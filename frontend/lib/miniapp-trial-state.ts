export type TrialService={id:number;server:string;username:string;[key:string]:unknown};
export type TrialOperation={id:number;status:string;result:{message?:string;services?:TrialService[]}};
export type TrialInfo={used:boolean;can_request:boolean;can_repeat:boolean;volume_gb:number;duration_days:number;server_count:number;services:TrialService[];operation:TrialOperation|null};

export function canRequestTrial(info:TrialInfo|null,op:TrialOperation|null):boolean{
 return !!info&&!info.used&&info.can_request&&info.server_count>0&&!['queued','processing'].includes(op?.status||'')&&(op?.status!=='done'||info.can_repeat);
}

export function trialServices(info:TrialInfo|null,op:TrialOperation|null):TrialService[]{
 const unique=new Map<number,TrialService>();
 for(const service of [...(info?.services||[]),...(op?.result.services||[])])unique.set(service.id,service);
 return Array.from(unique.values());
}
