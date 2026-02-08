package main

import (
    "context"
    "encoding/json"
    "net/http"
    "os"
    "time"
    _ "embed"
    "bytes"
    "strconv"
	"io"
	"mime/multipart"

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

		// --- PROXY UPLOAD TO FILE.IO ---
		//stream the file to file.io so don't use up Render's RAM
		file, err := fileHeader.Open()
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to open file"})
			return
		}
		defer file.Close()

		// Prepare request to file.io
		body := &bytes.Buffer{}
		writer := multipart.NewWriter(body)
		part, _ := writer.CreateFormFile("file", fileHeader.Filename)
		io.Copy(part, file) // Copy stream
		writer.Close()

		req, _ := http.NewRequest("POST", "https://file.io/?expires=1d", body)
		req.Header.Set("Content-Type", writer.FormDataContentType())

		client := &http.Client{Timeout: 60 * time.Second}
		resp, err := client.Do(req)
		if err != nil || resp.StatusCode != 200 {
			c.JSON(http.StatusBadGateway, gin.H{"error": "Failed to upload to intermediate storage"})
			return
		}
		defer resp.Body.Close()

		// Parse file.io response to get the URL
		var fileIoResp struct {
			Success bool   `json:"success"`
			Link    string `json:"link"`
		}
		json.NewDecoder(resp.Body).Decode(&fileIoResp)

		if !fileIoResp.Success {
			c.JSON(http.StatusBadGateway, gin.H{"error": "Intermediate storage rejected file"})
			return
		}

		// 3. Queue Job 
		jobID := uuid.New().String()
		jobData := map[string]interface{}{
			"id":           jobID,
			"download_url": fileIoResp.Link, 
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