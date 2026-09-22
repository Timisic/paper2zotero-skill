param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = New-Object System.Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')
$acl.AddAccessRule($rule)
# powershell.exe uses .NET Framework. Avoid module autoloading: callers may
# inherit a PowerShell 7 PSModulePath that prevents PS5's Set-Acl from loading.
[System.IO.File]::SetAccessControl($ConfigPath, $acl)
