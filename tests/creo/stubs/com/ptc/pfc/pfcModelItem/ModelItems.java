package com.ptc.pfc.pfcModelItem;

import java.util.*;

public class ModelItems {
    private final List<Dimension> items = new ArrayList<>();
    public void add(Dimension d) { items.add(d); }
    public int getarraysize() { return items.size(); }
    public Dimension get(int i) { return items.get(i); }
}
