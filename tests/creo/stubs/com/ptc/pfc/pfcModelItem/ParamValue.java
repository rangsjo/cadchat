package com.ptc.pfc.pfcModelItem;

public class ParamValue {
    private Double d;
    private String s;
    public ParamValue(Double d, String s) { this.d = d; this.s = s; }
    public double GetDoubleValue() throws Exception { if (d == null) throw new Exception("XBadGetParamValue"); return d; }
    public int GetIntValue() throws Exception { throw new Exception("XBadGetParamValue"); }
    public String GetStringValue() throws Exception { if (s == null) throw new Exception("XBadGetParamValue"); return s; }
    public boolean GetBoolValue() throws Exception { throw new Exception("XBadGetParamValue"); }
    public void SetDoubleValue(double v) { d = v; s = null; }
    public void SetStringValue(String v) { s = v; d = null; }
}
