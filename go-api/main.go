package main

import (
    "context"
    "encoding/json"
    "net/http"
    "os"
    "time"
    _ "embed"
    "fmt"
    "strconv"
	"io"

    "github.com/gin-gonic/gin"
    "github.com/go-redis/redis/v8"
    "github.com/google/uuid"
)

//go:embed index.html
var indexHTML []byte // variable for html file

// Define the data user sends 
type QuotationRequest struct {
    DownloadURL string `json:"download_url" binding:"required"`
    Material    string `json:"material"`
    LayerHeight float64 `json:"layer_height"`
    Infill      int    `json:"infill" binding:"required"`
    Rush        bool   `json:"rush"`
}

var ctx = context.Background()

func main() {
    // Connect to Redis
    // redisAddr := os.Getenv("REDIS_ADDR")
    // if redisAddr == "" {
    //     redisAddr = "localhost:6379"
    // }
    // rdb := redis.NewClient(&redis.Options{Addr: redisAddr})

    // Cloud URL Support (Supports Upstash/Render/AWS)
    redisURL := os.Getenv("REDIS_URL")
    var opts *redis.Options
    var err error

    if redisURL != "" {
        // Parse the full URL (rediss://user:pass@host:port)
        opts, err = redis.ParseURL(redisURL)
        if err != nil {
            panic("Invalid REDIS_URL: " + err.Error())
        }
    } else {
        // Fallback for local testing
        opts = &redis.Options{Addr: "localhost:6379"}
    }
    if err != nil {
		// We use panic here because the app cannot function without Redis
		panic("Failed to connect to Redis: " + err.Error())
	}
    rdb := redis.NewClient(opts)

    r := gin.Default()

    //serve frontend html
    r.GET("/", func(c *gin.Context) {
		c.Data(http.StatusOK, "text/html; charset=utf-8", indexHTML)
	})

    // Endpoint 1: Submit Job
    r.POST("/quote", func(c *gin.Context) {
        var req QuotationRequest
        if err := c.ShouldBindJSON(&req); err != nil {
            c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
            return
        }

        jobID := uuid.New().String()
        
        // Payload for the Python Worker
        jobData := map[string]interface{}{
            "id":           jobID,
            "download_url": req.DownloadURL,
            "material":     req.Material,
            "layer_height": req.LayerHeight,
            "infill":       req.Infill,
            "rush":         req.Rush,
        }
        jsonData, _ := json.Marshal(jobData)

        // Push to Redis List "print_jobs"
        if err := rdb.RPush(ctx, "print_jobs", jsonData).Err(); err != nil {
            c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to queue job"})
            return
        }

        // Set initial status
        rdb.Set(ctx, "status:"+jobID, "queued", 24*time.Hour)

        // Return the Ticket ID immediately
        c.JSON(http.StatusAccepted, gin.H{
            "job_id": jobID,
            "message": "Job queued successfully. Poll /status/" + jobID + " for results.",
        })
    })

    // Endpoint 2: Check Status (Polling)
    r.GET("/status/:id", func(c *gin.Context) {
        jobID := c.Param("id")

        // 1. Get the authoritative STATUS first
        status, err := rdb.Get(ctx, "status:"+jobID).Result()
        
        // Handle missing key: Job ID invalid or expired
        if err == redis.Nil {
            c.JSON(http.StatusNotFound, gin.H{"error": "Job not found"})
            return
        } else if err != nil {
            c.JSON(http.StatusInternalServerError, gin.H{"error": "Redis error"})
            return
        }

        // 2. Prepare the response
        response := gin.H{"status": status}

        // 3. If finished completed OR failed, attach the result data
        if status == "completed" || status == "failed" {
            res, err := rdb.Get(ctx, "result:"+jobID).Result()
            if err == nil {
                var resultJSON map[string]interface{}
                json.Unmarshal([]byte(res), &resultJSON)
                response["data"] = resultJSON
            }
        }

        c.JSON(http.StatusOK, response)
    })

    //Endpoint 3: Handle file uploads
    r.POST("/upload", func(c *gin.Context) {
		fileHeader, err := c.FormFile("file")
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "No file uploaded"})
			return
		}

		material := c.DefaultPostForm("material", "PLA")
        infillStr := c.DefaultPostForm("infill", "15")
		
		// Parse infill to int
		infill, err := strconv.Atoi(infillStr)
		if err != nil {
			infill = 15 // Fallback default
		}

		// --- PROXY UPLOAD TO TRANSFER.SH (More Reliable) ---
		file, err := fileHeader.Open()
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to open file"})
			return
		}
		defer file.Close()

		// transfer.sh uses PUT /{filename}
		// We use the original filename to keep the extension correct
		uploadURL := "https://transfer.sh/" + fileHeader.Filename
		
		req, _ := http.NewRequest("PUT", uploadURL, file)
		
		// Set content length if possible to help transfer.sh
		req.ContentLength = fileHeader.Size
		req.Header.Set("Content-Type", "application/octet-stream")

		client := &http.Client{Timeout: 120 * time.Second} // 2 mins for larger uploads
		resp, err := client.Do(req)
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": "Failed to connect to storage: " + err.Error()})
			return
		}
		defer resp.Body.Close()

		// transfer.sh returns the URL as plain text in the body
		responseBody, _ := io.ReadAll(resp.Body)
		downloadLink := string(responseBody)

		if resp.StatusCode != 200 || downloadLink == "" {
			// Log the actual error from the provider for debugging
			fmt.Printf("Storage Error: Status %d, Body: %s\n", resp.StatusCode, downloadLink)
			c.JSON(http.StatusBadGateway, gin.H{"error": "Storage provider rejected file"})
			return
		}
		
		// ----------------------------------------------------

		// 3. Queue Job 
		jobID := uuid.New().String()
		jobData := map[string]interface{}{
			"id":           jobID,
			"download_url": downloadLink, // Now using transfer.sh link
			"material":     material,
			"infill":       infill,
		}
		jsonData, _ := json.Marshal(jobData)
		rdb.RPush(ctx, "print_jobs", jsonData)
		rdb.Set(ctx, "status:"+jobID, "queued", 24*time.Hour)

		c.JSON(http.StatusAccepted, gin.H{"job_id": jobID, "message": "File uploaded"})
	})


    r.Run(":8000")
}