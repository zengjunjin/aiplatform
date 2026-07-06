$baseUrl = "http://localhost:8000/api/v1"

# 1. Login
Write-Host "=== 1. Logging in..."
$loginBody = @{
    username = "test@example.com"
    password = "test123456"
} | ConvertTo-Json

$loginResponse = Invoke-RestMethod -Uri "$baseUrl/auth/login" -Method Post -Body $loginBody -ContentType "application/json"
$token = $loginResponse.data.access_token
Write-Host "Login successful, token obtained: $($token.Substring(0, 30))..."

$headers = @{
    "Authorization" = "Bearer $token"
}

Write-Host ""

# 2. Test GET /documents (no kb_id)
Write-Host "=== 2. Test GET /documents (no kb_id) ==="
try {
    $response = Invoke-RestMethod -Uri "$baseUrl/documents" -Method Get -Headers $headers
    Write-Host "Status: 200"
    Write-Host "Response: $($response | ConvertTo-Json -Depth 10)"
} catch {
    Write-Host "Error: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
        Write-Host "Status Code: $statusCode"
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $body = $reader.ReadToEnd()
        Write-Host "Response Body: $body"
    }
}

Write-Host ""

# 3. Test GET /documents?kb_id=1
Write-Host "=== 3. Test GET /documents?kb_id=1 ==="
try {
    $response = Invoke-RestMethod -Uri "$baseUrl/documents?kb_id=1" -Method Get -Headers $headers
    Write-Host "Status: 200"
    Write-Host "Response: $($response | ConvertTo-Json -Depth 10)"
} catch {
    Write-Host "Error: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
        Write-Host "Status Code: $statusCode"
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $body = $reader.ReadToEnd()
        Write-Host "Response Body: $body"
    }
}

Write-Host ""
Write-Host "All tests completed!"