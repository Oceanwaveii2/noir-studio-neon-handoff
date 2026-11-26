/* Lossless script cells. Separators stay outside the editable field. */
(function (root) {
  function split(text) {
    const parts=text.split(/((?:\r\n|\r(?!\n)|\n)[\t ]*(?:\r\n|\r(?!\n)|\n)(?:(?:[\t ]*)(?:\r\n|\r(?!\n)|\n))*)/);
    return parts.filter((_,i)=>i%2===0).map((value,i)=>({text:value,gap:parts[2*i+1]||''}));
  }
  function join(blocks) { return blocks.map(b=>b.text+b.gap).join(''); }
  function offset(blocks,index,normalizedOffset) {
    const before=join(blocks.slice(0,index));
    const units=blocks[index].text.match(/\r\n|[\s\S]/g)||[];
    if (!Number.isInteger(normalizedOffset) || normalizedOffset<0 || normalizedOffset>units.length) throw Error('Invalid text position');
    const left=units[normalizedOffset-1],right=units[normalizedOffset];
    if (left && right && /^[\uD800-\uDBFF]$/.test(left) && /^[\uDC00-\uDFFF]$/.test(right)) throw Error('Choose a position outside the emoji');
    return Array.from(before+units.slice(0,normalizedOffset).join('')).length;
  }
  function graphemeBoundary(text, position) {
    const points=Array.from(text);
    if (!Number.isInteger(position) || position<0 || position>points.length) return false;
    if (!Intl.Segmenter) return /^[\x00-\x7f]*$/.test(text) && !(points[position-1]==='\r' && points[position]==='\n');
    const target=points.slice(0,position).join('').length;
    if (target===text.length) return true;
    return Array.from(new Intl.Segmenter(undefined,{granularity:'grapheme'}).segment(text)).some(s=>s.index===target);
  }
  function applyNormalizedEdit(original,value,preferred) {
    if(typeof original!=='string' || typeof value!=='string' || !['\n','\r','\r\n'].includes(preferred))throw Error('Invalid text edit');
    const units=original.match(/\r\n|[\s\S]/g)||[];
    const normalized=units.map(c=>c==='\r\n'||c==='\r'?'\n':c).join('');
    let prefix=0;while(prefix<normalized.length && prefix<value.length && normalized[prefix]===value[prefix])prefix++;
    let suffix=0;while(suffix<normalized.length-prefix && suffix<value.length-prefix && normalized[normalized.length-1-suffix]===value[value.length-1-suffix])suffix++;
    return units.slice(0,prefix).join('')+value.slice(prefix,value.length-suffix).replace(/\n/g,preferred)+units.slice(units.length-suffix).join('');
  }
  function kind(text) {
    const first=text.trim().split(/\r?\n/,1)[0];
    if (/^(?:INT\.|EXT\.|INT\/EXT\.|I\/E\.)\s/i.test(first)) return 'Scene';
    if (/^[A-Z][A-Z\d .'-]{1,30}(?::|$)/.test(first)) return 'Dialogue';
    return 'Action';
  }
  function inferLabel(text) {
    const source=text.trim();
    if(!source)return {label:'Narrator',kind:'narrator'};
    if(/^(?:#{1,6}\s*)?(?:\*\*)?(?:INT\.|EXT\.|INT\/EXT\.|I\/E\.|SCENE\s+\d+\b)/i.test(source))return {label:'Scene',kind:'narrator'};
    const cue=source.match(/^([A-Z][A-Z0-9 .’'\-]{1,38})\s*:\s*/);
    if(cue)return {label:cue[1].trim(),kind:'character'};
    const fountain=source.match(/^([A-Z][A-Z0-9 .’'\-]{1,38})\s*\r?\n(?=\S)/);
    if(fountain)return {label:fountain[1].trim(),kind:'character'};
    const attributed=source.match(/^[“"][^”"\r\n]+[”"]\s*,?\s+(\p{Lu}[\p{L}’'\-]*(?:\s+\p{Lu}[\p{L}’'\-]*)?)\s+(?:said|asked|replied|answered|whispered|shouted|called|muttered|declared|gasped|yelled|announced|exclaimed)\b/u);
    if(attributed)return {label:attributed[1],kind:'character'};
    if(/^[“"]/.test(source))return {label:'Dialogue',kind:'character'};
    return {label:'Narrator',kind:'narrator'};
  }
  function isSeparator(text) {
    const trimmed=(text||'').trim();
    return /^(?:\*{3,}|-{3,}|_{3,}|\*\s+\*\s+\*)$/.test(trimmed);
  }
  function isSceneHeading(text, notebookItem) {
    if (notebookItem && notebookItem.kind==='scene-heading') return true;
    const source=(text||'').trim();
    if (!source) return false;
    if (/^#{1,6}\s+\S/.test(source)) return true;
    return /^(?:#{1,6}\s*)?(?:\*\*)?(?:INT\.|EXT\.|INT\/EXT\.|I\/E\.|SCENE\s+\d+\b|CHAPTER\s+\d+\b|PROLOGUE\b|EPILOGUE\b|ACT\s+[IVX\d]+\b)/i.test(source);
  }
  function describeBlock(text, notebookItem, index) {
    const pos=Number.isInteger(index)?index:0;
    if (isSeparator(text)) {
      return {groupKey:'separator:'+pos,kind:'separator',label:'Separator',speaker:null,form:null,canGroup:false};
    }
    if (isSceneHeading(text,notebookItem)) {
      return {groupKey:'scene-heading:'+pos,kind:'scene-heading',label:'Scene',speaker:null,form:null,canGroup:false};
    }
    if (notebookItem && notebookItem.kind && notebookItem.kind!=='unresolved') {
      if (notebookItem.kind==='character') {
        if (notebookItem.speaker) {
          const speaker=notebookItem.speaker,form=notebookItem.form||null;
          return {groupKey:'character:'+speaker+'::'+(form||''),kind:'character',label:speaker,speaker,form,canGroup:true};
        }
        return {groupKey:'character-anon:'+pos,kind:'character',label:'Dialogue',speaker:null,form:notebookItem.form||null,canGroup:false};
      }
      if (notebookItem.kind==='narrator') {
        return {groupKey:'narrator',kind:'narrator',label:'Narrator',speaker:null,form:null,canGroup:true};
      }
      return {groupKey:notebookItem.kind+':'+pos,kind:notebookItem.kind,label:notebookItem.kind,speaker:notebookItem.speaker||null,form:notebookItem.form||null,canGroup:false};
    }
    const inferred=inferLabel(text);
    if (inferred.kind==='character') {
      if (inferred.label==='Dialogue') {
        return {groupKey:'dialogue:'+pos,kind:'character',label:'Dialogue',speaker:null,form:null,canGroup:false};
      }
      return {groupKey:'inferred-character:'+inferred.label.toLowerCase(),kind:'character',label:inferred.label,speaker:null,form:null,canGroup:true};
    }
    return {groupKey:'narrator',kind:'narrator',label:'Narrator',speaker:null,form:null,canGroup:true};
  }
  function alignedNotebookBlocks(text, notebookBlocks) {
    const rawCells=split(text);
    if (!Array.isArray(notebookBlocks) || !notebookBlocks.length) return rawCells.map(()=>[]);
    const joinedNb=notebookBlocks.map(b=>b?.text||'').join('');
    if (joinedNb!==text) return rawCells.map(()=>[]);
    const nbSpans=[];
    let nbOffset=0;
    for (const item of notebookBlocks) {
      const len=Array.from(item.text||'').length;
      nbSpans.push({item,start:nbOffset,end:nbOffset+len});
      nbOffset+=len;
    }
    const aligned=[];
    let cellOffset=0;
    for (const cell of rawCells) {
      const len=Array.from(cell.text+cell.gap).length;
      const cellEnd=cellOffset+len;
      const items=len===0
        ? nbSpans.filter(s=>s.start===cellOffset && s.end===cellOffset).map(s=>s.item)
        : nbSpans.filter(s=>s.start<cellEnd && s.end>cellOffset).map(s=>s.item);
      aligned.push(items);
      cellOffset=cellEnd;
    }
    return aligned;
  }
  function group(text, notebookBlocks) {
    const rawCells=split(text);
    const aligned=alignedNotebookBlocks(text,notebookBlocks);
    const groups=[];
    let rawStart=0;
    for (let i=0;i<rawCells.length;i++) {
      const raw=rawCells[i];
      const items=aligned[i]||[];
      const item=items[0]||null;
      const desc=describeBlock(raw.text,item,i);
      const prev=groups[groups.length-1];
      const sameGroup=Boolean(prev && prev.canGroup && desc.canGroup && prev.groupKey===desc.groupKey && prev.parts[prev.parts.length-1].gap!=='');
      const partEntry={rawIndex:i,text:raw.text,gap:raw.gap,items:items.slice(),meta:desc};
      if (sameGroup) {
        const prevLast=prev.parts[prev.parts.length-1];
        prev.text+=prevLast.gap+raw.text;
        prev.gap=raw.gap;
        prev.parts.push(partEntry);
        for (const nb of items) {
          if (nb && !prev.items.some(existing=>existing===nb || (existing.id && existing.id===nb.id))) prev.items.push(nb);
        }
        prev.item=prev.items[0]||null;
      } else {
        groups.push({
          text:raw.text,
          gap:raw.gap,
          groupKey:desc.groupKey,
          kind:desc.kind,
          label:desc.label,
          speaker:desc.speaker,
          form:desc.form,
          canGroup:desc.canGroup,
          item:item,
          items:items.slice(),
          start:rawStart,
          parts:[partEntry]
        });
      }
      rawStart+=Array.from(raw.text+raw.gap).length;
    }
    return groups;
  }
  function blockAtOffset(groupCell, localCodePointOffset) {
    const text=(groupCell && groupCell.text) || '';
    const totalLen=Array.from(text).length;
    const pos=Number.isInteger(localCodePointOffset)?Math.max(0,Math.min(totalLen,localCodePointOffset)):0;
    const parts=groupCell && Array.isArray(groupCell.parts) && groupCell.parts.length ? groupCell.parts : null;
    if (!parts) {
      const items=(groupCell && Array.isArray(groupCell.items) && groupCell.items.length)
        ? groupCell.items
        : (groupCell && groupCell.item ? [groupCell.item] : []);
      return {partIndex:0,part:null,item:items[0]||null,items,localStart:0,localEnd:totalLen};
    }
    let cursor=0;
    for (let k=0;k<parts.length;k++) {
      const part=parts[k];
      const textLen=Array.from(part.text||'').length;
      const gapLen=(k<parts.length-1)?Array.from(part.gap||'').length:0;
      const partEnd=cursor+textLen+gapLen;
      if (pos<partEnd || k===parts.length-1) {
        return {partIndex:k,part,item:(part.items&&part.items[0])||groupCell.item||null,items:part.items||[],localStart:cursor,localEnd:partEnd};
      }
      cursor=partEnd;
    }
    return {partIndex:0,part:parts[0],item:groupCell.item||null,items:groupCell.items||[],localStart:0,localEnd:totalLen};
  }
  const api={split,join,offset,kind,inferLabel,isSeparator,isSceneHeading,describeBlock,alignedNotebookBlocks,group,blockAtOffset,graphemeBoundary,applyNormalizedEdit};
  if (typeof module!=='undefined') module.exports=api; else root.ComposeBlocks=api;
})(globalThis);
