package com.ptc.pfc.pfcModelItem;

public class Dimension {
    private final String symbol;
    private double value;
    public Dimension(String symbol, double value) { this.symbol = symbol; this.value = value; }
    public String GetSymbol() { return symbol; }
    public double GetDimValue() { return value; }
    public void SetDimValue(double v) { value = v; }
}
