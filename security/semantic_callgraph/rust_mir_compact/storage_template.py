"""Inlined into the candidate so one source fingerprint binds all solver code."""
def make_facts(stats):
    from collections import OrderedDict
    class Bits:
        __slots__=('blocks','count')
        def __init__(self,blocks,count):self.blocks=blocks;self.count=count
    empty=Bits((),0)
    identities={};tokens_by_kind=defaultdict(list);singletons={}
    unions=OrderedDict();limit=16384
    def encode(token):
        found=identities.get(token)
        if found is None:
            kind=token[0];index=len(tokens_by_kind[kind]);tokens_by_kind[kind].append(token)
            found=(kind,index);identities[token]=found
        return found
    def join(left,right):
        stats['bitset_union_queries']+=1
        if left is right or not right.count:return left
        if not left.count:return right
        key=(left,right)
        cached=unions.get(key)
        if cached is not None:
            unions.move_to_end(key);stats['bitset_union_cache_hits']+=1;return cached
        a=left.blocks;b=right.blocks;i=j=0;out=[];added=0
        while i<len(a) and j<len(b):
            ai,av=a[i];bi,bv=b[j]
            if ai==bi:
                bits=av|bv;added+=(bits^av).bit_count();out.append((ai,bits));i+=1;j+=1
            elif ai<bi:out.append(a[i]);i+=1
            else:out.append(b[j]);added+=bv.bit_count();j+=1
            stats['bitset_blocks_processed']+=1
        out.extend(a[i:]);out.extend(b[j:]);added+=sum(v.bit_count() for _,v in b[j:])
        result=Bits(tuple(out),left.count+added) if added else left
        unions[key]=result
        if len(unions)>limit:unions.popitem(last=False)
        return result
    def packed(incoming):
        if isinstance(incoming,Facts):return incoming.parts
        if isinstance(incoming,(set,frozenset,tuple,list)) and len(incoming)==1:
            token=next(iter(incoming));cached=singletons.get(token)
            if cached is None:
                kind,index=encode(token)
                cached={kind:Bits(((index>>8,1<<(index&255)),),1)};singletons[token]=cached
            return cached
        temporary=defaultdict(dict)
        for token in incoming:
            kind,index=encode(token);block=index>>8;bit=1<<(index&255)
            temporary[kind][block]=temporary[kind].get(block,0)|bit
        return {k:Bits(tuple(sorted(blocks.items())),sum(v.bit_count() for v in blocks.values())) for k,blocks in temporary.items()}
    class Facts:
        __slots__=('cell','parts','version')
        def __init__(self,cell=None):self.cell=cell;self.parts={};self.version=0
        def __len__(self):return sum(v.count for v in self.parts.values())
        def __iter__(self):
            for kind in self.parts:yield from self.tokens(kind)
        def __contains__(self,token):
            found=identities.get(token)
            if found is None:return False
            kind,index=found;bits=self.parts.get(kind,empty);block=index>>8
            # Sorted immutable blocks; binary lookup, no decoded memberships.
            lo=0;hi=len(bits.blocks)
            while lo<hi:
                mid=(lo+hi)//2;key,value=bits.blocks[mid]
                if key<block:lo=mid+1
                elif key>block:hi=mid
                else:return bool(value & (1<<(index&255)))
            return False
        def tokens(self,kind):
            stats['kind_lookups']+=1
            table=tokens_by_kind[kind]
            for block,bits in self.parts.get(kind,empty).blocks:
                while bits:
                    bit=bits & -bits;yield table[(block<<8)+bit.bit_length()-1];bits^=bit
        def merge(self,incoming):
            additions=0
            for kind,source in packed(incoming).items():
                old=self.parts.get(kind,empty);new=join(old,source)
                if new is not old:self.parts[kind]=new;additions+=new.count-old.count
            if additions:
                self.version+=1
                if self.cell is not None:stats['points_to_additions']+=additions
            return bool(additions)
        def update(self,incoming):self.merge(incoming)
    return Facts
