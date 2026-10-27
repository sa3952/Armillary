(function attachPrivacyLifecycle(root,factory){const api=factory();if(typeof module==="object"&&module.exports)module.exports=api;if(root)root.PrivacyLifecycle=api;})(typeof globalThis!=="undefined"?globalThis:this,function buildPrivacyLifecycle(){"use strict";function createSensitiveDataLifecycle(options={}){const revokeObjectUrl=typeof options.revokeObjectUrl==="function"?options.revokeObjectUrl:(url)=>URL.revokeObjectURL(url);let canonicalDocument=null;let activeRequest=null;const objectUrls=new Set();const sectionNodes=new Set();function setCanonicalDocument(documentModel){if(!documentModel||typeof documentModel!=="object"||Array.isArray(documentModel)){throw new Error("缺少可追溯的 canonical document。");}
canonicalDocument=documentModel;}
function requireCanonicalDocument(){if(!canonicalDocument){throw new Error("敏感計算資料已清除或尚未完成計算。");}
return canonicalDocument;}
function registerSectionNode(node){if(!node||typeof node!=="object"||Array.isArray(node)){throw new Error("無法登記輸出區段的敏感資料引用。");}
sectionNodes.add(node);}
function registerObjectUrl(url){if(typeof url!=="string"||!url){throw new Error("無法登記空白的 Blob URL。");}
objectUrls.add(url);return url;}
function deliverDownload(doc,blob,filename){const win=doc.defaultView;const url=registerObjectUrl(win.URL.createObjectURL(blob));const anchor=doc.createElement("a");anchor.href=url;anchor.download=filename;anchor.hidden=true;doc.body.appendChild(anchor);anchor.click();anchor.remove();win.setTimeout(()=>releaseObjectUrl(url),0);}
function releaseObjectUrl(url){if(!objectUrls.delete(url))return false;try{revokeObjectUrl(url);}catch(_error){}
return true;}
function beginRequest(controller){if(!controller||typeof controller.abort!=="function"){throw new Error("敏感 request 必須使用可中止的 AbortController。");}
if(activeRequest){try{activeRequest.controller.abort();}catch(_error){}}
const token=Object.freeze({});activeRequest={controller,token};return token;}
function isCurrentRequest(token){return Boolean(activeRequest&&activeRequest.token===token);}
function finishRequest(token){if(!isCurrentRequest(token))return false;activeRequest=null;return true;}
function scheduleAbort(controller,delayMs,scheduleTimeout=setTimeout){if(!controller||typeof controller.abort!=="function"){throw new Error("逾時控制必須使用可中止的 AbortController。");}
if(!Number.isFinite(delayMs)||delayMs<=0){throw new Error("逾時上限必須是正數。");}
let timedOut=false;const handle=scheduleTimeout(()=>{timedOut=true;try{controller.abort();}catch(_error){}},delayMs);return Object.freeze({handle,didTimeout:()=>timedOut});}
function beginTimedRequest(delayMs,scheduleTimeout,Controller=AbortController){const controller=new Controller();const token=beginRequest(controller);return{controller,token,timeout:scheduleAbort(controller,delayMs,scheduleTimeout)};}
function abortActiveRequest(){if(!activeRequest)return false;const request=activeRequest;activeRequest=null;try{request.controller.abort();}catch(_error){}
return true;}
function clear(){const receipt={canonical_document_cleared:canonicalDocument!==null,object_urls_revoked:objectUrls.size,section_references_cleared:sectionNodes.size,request_aborted:activeRequest!==null,};canonicalDocument=null;if(activeRequest){const request=activeRequest;activeRequest=null;try{request.controller.abort();}catch(_error){}}
sectionNodes.clear();for(const url of Array.from(objectUrls)){releaseObjectUrl(url);}
return receipt;}
function inspect(){return{has_canonical_document:canonicalDocument!==null,active_object_url_count:objectUrls.size,registered_section_count:sectionNodes.size,request_active:activeRequest!==null,};}
return Object.freeze({setCanonicalDocument,requireCanonicalDocument,registerSectionNode,registerObjectUrl,releaseObjectUrl,deliverDownload,beginRequest,isCurrentRequest,finishRequest,scheduleAbort,beginTimedRequest,abortActiveRequest,clear,inspect,});}
function isJsonResponse(response){const mediaType=(response.headers.get("Content-Type")||"").split(";",1)[0].trim().toLowerCase();return mediaType==="application/json"||mediaType.endsWith("+json");}
function postJson(win,url,payload,signal){return win.fetch(url,{method:"POST",headers:{"Content-Type":"application/json",Accept:"application/json"},body:JSON.stringify(payload),signal}).then((response)=>{if(response.ok&&!isJsonResponse(response)){return{response,body:null,invalidJsonMedia:true};}
return response.json().catch(()=>null).then((body)=>({response,body,invalidJsonMedia:false}));});}
return Object.freeze({createSensitiveDataLifecycle,postJson});});
