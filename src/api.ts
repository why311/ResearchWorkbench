export async function api(path: string, options: RequestInit = {}) {
  const response = await fetch('/api' + path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请重试');
  return data;
}

export const post=(path:string,body:object={})=>api(path,{method:'POST',body:JSON.stringify(body)});
export type ModuleProps={project:{id:string;documents:{id:string;title:string;pages:number}[]};busy:string;action:(key:string,task:()=>Promise<any>)=>Promise<void>};
