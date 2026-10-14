package com.ptc.pfc.pfcModelItem;

public class Parameter {
    private final String name;
    private ParamValue value;
    public Parameter(String name, ParamValue value) { this.name = name; this.value = value; }
    public String GetName() { return name; }
    public ParamValue GetValue() { return value; }
    public void SetValue(ParamValue v) { value = v; }
}
