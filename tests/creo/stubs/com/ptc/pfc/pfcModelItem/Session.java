package com.ptc.pfc.pfcModelItem;

public class Session {
    public Model GetCurrentModel() { return "true".equals(System.getProperty("fake.nomodel")) ? null : Model.INSTANCE; }
}
