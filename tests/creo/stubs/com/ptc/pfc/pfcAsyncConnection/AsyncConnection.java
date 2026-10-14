package com.ptc.pfc.pfcAsyncConnection;

public class AsyncConnection {
    public com.ptc.pfc.pfcModelItem.Session GetSession() { return new com.ptc.pfc.pfcModelItem.Session(); }
    public void Disconnect(Integer timeout) { }
    public void End() { }
    public boolean IsRunning() { return true; }
}
