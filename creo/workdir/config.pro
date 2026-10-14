! Read by Creo when it is started from this folder (creo\start.cmd does that). Plain Creo configuration options.
!
! A failed regeneration normally opens a modal "Resolve Feature" dialog, which blocks every API call until someone
! clicks it. With this option a bad parameter value just reports a failure to the link.
regen_failure_handling no_resolve_mode
!
! Protocol used by the STEP export (AP214 keeps names and the assembly tree). If your Creo rejects the value, delete the line.
step_export_format ap214_is
