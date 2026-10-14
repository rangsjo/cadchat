package com.ptc.pfc.pfcModelItem;

import java.util.*;

public class Parameters {
    public final List<Parameter> items = new ArrayList<>();
    public void add(Parameter p) { items.add(p); }
    public int getarraysize() { return items.size(); }
    public Parameter get(int i) { return items.get(i); }
}
