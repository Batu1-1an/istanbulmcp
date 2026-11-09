"""Extract bounded source statements from scoped event text; never infer guarantees."""
from __future__ import annotations
import html
import re
from html.parser import HTMLParser
from app.core.events import PublishedEventCondition
from app.services.places import normalize_place

TOPICS = ('reservation','refund_exchange','accessibility','language','ticket_requirement',
          'materials','certificate','photography','seating','sensory','fees')
PATTERNS = {
 'fees':r'hizmet bedeli|servis bedeli|service fee',
 'reservation':r'\brezervasyon\b|\bkayit\b|\bregistration\b|\bbooking\b',
 'refund_exchange':r'\biade\w*|\bdegisim\b|\bdegisiklik\b|\brefund\b|\bexchange\b',
 'accessibility':r'^erisilebilirlik\s*:|tekerlekli|basamaksiz|wheelchair|accessible|refakatci|engelli.{0,40}(?:giris|erisim|tuvalet|koltuk)',
 'language':r'\bdil(?:i)?\s*:\s*(?:ingilizce|turkce|english|fransizca)|(?:oyun|gosteri|etkinlik|performans).{0,45}(?:ingilizce|turkce|english|francais)|altyazi|ustyazi|surtitles|subtitles',
 'ticket_requirement':r'bilete tabi|bilet (?:almak|alimi|alinmasi).{0,40}(?:zorunlu|gerek)|ticket required',
 'materials':r'\bmalzeme|\bekipman|\bmaterials?\b|\bequipment\b',
 'certificate':r'\bsertifika|\bcertificate\b',
 'photography':r'fotograf|video cekim|photograph|recording',
 'seating':r'\bayakta\b|\boturma\b|\bkoltuk|\bseating\b|\bseated\b',
 'sensory':r'yuksek ses|ses seviyesi|yogun isik|stroboskop|yanip sonen|duyusal|sensory|flashing|loud sound',
}


def parse_event_conditions(sections: list[tuple[str,str]], url: str, diagnostics=None) -> list[PublishedEventCondition]:
    result=[];seen=set();remaining=64000
    for section,raw in sections:
        if diagnostics is not None and len(raw)>remaining:diagnostics['truncated']=True
        raw=raw[:remaining];remaining-=len(raw)
        raw=re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>','',raw,flags=re.I|re.S)
        raw=re.sub(r'</(?:li|p|div)>|<br\s*/?>','\n',raw,flags=re.I)
        text=html.unescape(re.sub(r'<[^>]+>',' ',raw))
        for sentence in re.split(r'\n+|(?<=[.!?;])\s+',text):
            statement=' '.join(sentence.split())
            # Never silently truncate a policy, possibly removing a negation or exception.
            if len(statement)>600:
                if diagnostics is not None:diagnostics['truncated']=True
                continue
            if len(statement)<5:continue
            folded=normalize_place(statement)
            patterns=dict(PATTERNS)
            if section=='rules' and folded not in {'etkinlik kurallari','kurallar','event rules'} and not any(re.search(pattern,folded) for pattern in PATTERNS.values()):
                patterns['other']=r'.'
            for topic,pattern in patterns.items():
                key=(topic,statement)
                if key not in seen and re.search(pattern,folded):
                    result.append(PublishedEventCondition(topic=topic,statement=statement,
                                  source_url=url,source_section=section))
                    seen.add(key)
                    if len(result)==60:
                        if diagnostics is not None:diagnostics['truncated']=True
                        return result
        if remaining<=0:break
    return result


def conditions_output(rows, *, checked: bool, limit: int = 12, observed_at=None, stale=False, extraction_truncated=False) -> dict:
    topics={r.topic for r in rows}
    return {'status':'expired' if stale else 'inspected' if checked else 'unknown',
            'source_observed_at':observed_at if checked or stale else None,
            'statements':[r.model_dump() for r in rows[:limit]],
            'truncated':extraction_truncated or len(rows)>limit,
            'unverified_topics':[t for t in TOPICS if t not in topics],
            'statements_are_source_claims':True,
            'personal_eligibility_verified':False}


def published_fees_included(conditions):
    values=set()
    for c in conditions:
        text=normalize_place(c.statement)
        if re.fullmatch(r'(?:tum )?bilet fiyatlarina (?:hizmet|servis) bedeli dahildir',text):values.add(True)
        if re.fullmatch(r'(?:tum )?bilet fiyatlarina (?:hizmet|servis) bedeli dahil degildir',text):values.add(False)
    return next(iter(values)) if len(values)==1 else None


class _RulesBlockParser(HTMLParser):
    """Fallback for the provider's explicit legacy rules container IDs."""
    def __init__(self):
        super().__init__(convert_charrefs=False);self.root=None;self.depth=0;self.parts=[];self.blocks=[]
    def handle_starttag(self,tag,attrs):
        if self.root is None and tag in {'div','section'} and dict(attrs).get('id') in {'kurallar_section','kurallar'}:
            self.root=tag;self.depth=1;self.parts=[];return
        if self.root:
            if tag==self.root:self.depth+=1
            self.parts.append(self.get_starttag_text())
    def handle_endtag(self,tag):
        if self.root:
            if tag==self.root:self.depth-=1
            if not self.depth:
                self.blocks.append(''.join(self.parts));self.root=None;return
            self.parts.append('</'+tag+'>')
    def handle_data(self,data):
        if self.root:self.parts.append(data)
    def handle_entityref(self,name):
        if self.root:self.parts.append('&'+name+';')
    def handle_charref(self,name):
        if self.root:self.parts.append('&#'+name+';')


def legacy_rules_sections(html):
    parser=_RulesBlockParser();parser.feed(html)
    return [('rules',block) for block in parser.blocks[:2]]
