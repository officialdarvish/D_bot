import {createElement,Fragment,type ReactNode} from 'react';
/** Render only text and safe Telegram formatting; never create links/media or use innerHTML. */
export function BotTemplatePreview({text}:{text:string}){
 type Node={tag:string;children:(string|Node)[]};
 const root:Node={tag:'',children:[]},stack=[root];
 const allowed:Record<string,string>={b:'b',strong:'strong',i:'i',em:'em',u:'u',s:'s',strike:'s',del:'del',code:'code',pre:'pre',blockquote:'blockquote',a:'span','tg-spoiler':'span'};
 const plain=(value:string)=>value.replace(/&(amp|lt|gt|quot|apos);/g,(_,key:string)=>({amp:'&',lt:'<',gt:'>',quot:'"',apos:"'"}[key]||''));
 for(const part of text.split(/(<\/?[a-zA-Z][^>]*>)/g)){
  const match=part.match(/^<(\/?)([a-zA-Z-]+)(?:\s[^<>]*)?\s*\/?>$/);
  if(!match){stack[stack.length-1].children.push(plain(part));continue}
  const tag=match[2].toLowerCase();
  if(tag==='br'){stack[stack.length-1].children.push('\n');continue}
  if(!allowed[tag]){stack[stack.length-1].children.push(part);continue}
  if(match[1]){if(stack.length>1&&stack[stack.length-1].tag===tag)stack.pop();else stack[stack.length-1].children.push(part)}
  else{const node:Node={tag,children:[]};stack[stack.length-1].children.push(node);stack.push(node)}
 }
 const render=(node:Node):ReactNode=>node.children.map((child,index)=>typeof child==='string'?child:createElement(allowed[child.tag],{key:index,...(child.tag==='a'?{className:'cj-preview-link'}:{})},render(child)));
 return <Fragment>{render(root)}</Fragment>;
}
