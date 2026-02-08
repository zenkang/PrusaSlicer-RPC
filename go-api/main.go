package main

import (
    "context"
    "encoding/json"
    "net/http"
    "os"
    "time"

    "github.com/gin-gonic/gin"
    "github.com/go-redis/redis/v8"
    "github.com/google/uuid"
)

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
    redisAddr := os.Getenv("REDIS_ADDR")
    if redisAddr == "" {
        redisAddr = "localhost:6379"
    }
    rdb := redis.NewClient(&redis.Options{Addr: redisAddr})

    r := gin.Default()

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

        // Check if result exists
        result, err := rdb.Get(ctx, "result:"+jobID).Result()
        if err == nil {
            // Job is done! Return the full JSON result
            var resultJSON map[string]interface{}
            json.Unmarshal([]byte(result), &resultJSON)
            c.JSON(http.StatusOK, gin.H{"status": "completed", "data": resultJSON})
            return
        }

        // If no result, check status
        status, err := rdb.Get(ctx, "status:"+jobID).Result()
        if err == redis.Nil {
            c.JSON(http.StatusNotFound, gin.H{"status": "unknown_id"})
            return
        }

        c.JSON(http.StatusOK, gin.H{"status": status}) // Returns "queued" or "processing"
    })

    r.Run(":8000")
}