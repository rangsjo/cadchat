package com.ptc.pfc.pfcAsyncConnection;

/** Test double for PTC's J-Link async connection (only what CreoBridge calls). */
public class pfcAsyncConnection {
    public static AsyncConnection AsyncConnection_Connect(String display, String user, String textPath, Integer timeout) throws Exception {
        if (!"true".equals(System.getProperty("fake.creo.running", "true"))) throw new Exception("XToolkitNotFound: no Creo Parametric process found");
        return new AsyncConnection();
    }
    public static AsyncConnection AsyncConnection_Start(String cmd, String textPath) throws Exception {
        System.setProperty("fake.started", cmd);
        return new AsyncConnection();
    }
}
