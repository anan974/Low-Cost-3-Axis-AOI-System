#include "st7735_fast.h"
#include <string.h>

#define LINE_BUF_SIZE ST7735_WIDTH
static uint16_t line_buffer[LINE_BUF_SIZE];
static volatile uint8_t dma_busy = 0;

void HAL_SPI_TxCpltCallback(SPI_HandleTypeDef *hspi) {
    if (hspi->Instance == hspi1.Instance) {
        dma_busy = 0;
    }
}

static void ST7735_WriteCmd(uint8_t cmd) {
    ST7735_CMD();
    HAL_SPI_Transmit(&hspi1, &cmd, 1, HAL_MAX_DELAY);
}

static void ST7735_WriteData(uint8_t *data, uint16_t len) {
    ST7735_DATA();
    HAL_SPI_Transmit(&hspi1, data, len, HAL_MAX_DELAY);
}

static void ST7735_WriteDataDMA(uint16_t *data, uint16_t len) {
    ST7735_DATA();
    dma_busy = 1;
    HAL_SPI_Transmit_DMA(&hspi1, (uint8_t *)data, len * 2);
}

void ST7735_Init(void) {
    HAL_Delay(100);
    
    ST7735_RESET_ON();
    HAL_Delay(10);
    ST7735_RESET_OFF();
    HAL_Delay(120);
    
    ST7735_Select();
    
    ST7735_WriteCmd(ST7735_SLPOUT);
    HAL_Delay(120);
    
    ST7735_WriteCmd(ST7735_FRMCTR1);
    uint8_t frmctr1[] = {0x01, 0x2C, 0x2D};
    ST7735_WriteData(frmctr1, 3);
    
    ST7735_WriteCmd(ST7735_FRMCTR2);
    uint8_t frmctr2[] = {0x01, 0x2C, 0x2D};
    ST7735_WriteData(frmctr2, 3);
    
    ST7735_WriteCmd(ST7735_FRMCTR3);
    uint8_t frmctr3[] = {0x01, 0x2C, 0x2D, 0x01, 0x2C, 0x2D};
    ST7735_WriteData(frmctr3, 6);
    
    ST7735_WriteCmd(ST7735_INVOFF);
    
    ST7735_WriteCmd(ST7735_DISSET5);
    uint8_t disset5[] = {0x15};
    ST7735_WriteData(disset5, 1);
    
    ST7735_WriteCmd(ST7735_PWCTR1);
    uint8_t pwctr1[] = {0x02, 0x70};
    ST7735_WriteData(pwctr1, 2);
    
    ST7735_WriteCmd(ST7735_PWCTR2);
    uint8_t pwctr2[] = {0x05};
    ST7735_WriteData(pwctr2, 1);
    
    ST7735_WriteCmd(ST7735_PWCTR3);
    uint8_t pwctr3[] = {0x0A, 0x00};
    ST7735_WriteData(pwctr3, 2);
    
    ST7735_WriteCmd(ST7735_PWCTR4);
    uint8_t pwctr4[] = {0x8A, 0x2A};
    ST7735_WriteData(pwctr4, 2);
    
    ST7735_WriteCmd(ST7735_PWCTR5);
    uint8_t pwctr5[] = {0x8A, 0xEE};
    ST7735_WriteData(pwctr5, 2);
    
    ST7735_WriteCmd(ST7735_VMCTR1);
    uint8_t vmctr1[] = {0x0E};
    ST7735_WriteData(vmctr1, 1);
    
    ST7735_WriteCmd(ST7735_COLMOD);
    uint8_t colmod[] = {0x05};
    ST7735_WriteData(colmod, 1);
    
    ST7735_WriteCmd(ST7735_GMCTRP1);
    uint8_t gmctrp[] = {0x02, 0x1C, 0x07, 0x12, 0x37, 0x32, 0x29, 0x2D, 0x29, 0x25, 0x2B, 0x39, 0x00, 0x01, 0x03, 0x10};
    ST7735_WriteData(gmctrp, 16);
    
    ST7735_WriteCmd(ST7735_GMCTRN1);
    uint8_t gmctrn[] = {0x03, 0x1D, 0x07, 0x06, 0x2E, 0x2C, 0x29, 0x2D, 0x2E, 0x2E, 0x37, 0x3F, 0x00, 0x00, 0x02, 0x10};
    ST7735_WriteData(gmctrn, 16);
    
    ST7735_WriteCmd(ST7735_MADCTL);
    uint8_t madctl[] = {ST7735_MADCTL_MV | ST7735_MADCTL_RGB};
    ST7735_WriteData(madctl, 1);
    
    ST7735_DisplayOn();
    
    ST7735_Unselect();
}

void ST7735_DisplayOn(void) {
    ST7735_Select();
    ST7735_WriteCmd(ST7735_DISPON);
    ST7735_Unselect();
    HAL_Delay(100);
}

void ST7735_DisplayOff(void) {
    ST7735_Select();
    ST7735_WriteCmd(ST7735_DISPOFF);
    ST7735_Unselect();
}

void ST7735_Invert(bool enable) {
    ST7735_Select();
    ST7735_WriteCmd(enable ? ST7735_INVON : ST7735_INVOFF);
    ST7735_Unselect();
}

void ST7735_BeginFrame(void) {
    ST7735_Select();
    
    ST7735_WriteCmd(ST7735_CASET);
    uint8_t caset[] = {0x00, 0x00, 0x00, ST7735_WIDTH - 1};
    ST7735_WriteData(caset, 4);
    
    ST7735_WriteCmd(ST7735_RASET);
    uint8_t raset[] = {0x00, 0x00, 0x00, ST7735_HEIGHT - 1};
    ST7735_WriteData(raset, 4);
    
    ST7735_WriteCmd(ST7735_RAMWR);
}

void ST7735_PushLine(uint16_t *lineBuf) {
    while (dma_busy);
    memcpy(line_buffer, lineBuf, LINE_BUF_SIZE * 2);
    ST7735_WriteDataDMA(line_buffer, LINE_BUF_SIZE);
}

void ST7735_WaitFrameDone(void) {
    while (dma_busy);
}

void ST7735_EndFrame(void) {
    ST7735_WaitFrameDone();
    ST7735_Unselect();
}

void ST7735_DrawPixel(uint16_t x, uint16_t y, uint16_t color) {
    if (x >= ST7735_WIDTH || y >= ST7735_HEIGHT) return;
    
    ST7735_Select();
    
    ST7735_WriteCmd(ST7735_CASET);
    uint8_t caset[] = {0x00, x, 0x00, x};
    ST7735_WriteData(caset, 4);
    
    ST7735_WriteCmd(ST7735_RASET);
    uint8_t raset[] = {0x00, y, 0x00, y};
    ST7735_WriteData(raset, 4);
    
    ST7735_WriteCmd(ST7735_RAMWR);
    ST7735_WriteData((uint8_t *)&color, 2);
    
    ST7735_Unselect();
}

static void ST7735_RenderChar(uint16_t x, uint16_t y, char c, FontDef font, uint16_t fg, uint16_t bg) {
    if (c < 32 || c > 126) return;
    
    uint16_t char_idx = c - 32;
    
    for (uint16_t py = 0; py < font.height; py++) {
        uint16_t idx = char_idx * font.height + py;
        uint16_t char_data = font.data[idx];
        
        for (uint16_t px = 0; px < font.width; px++) {
            uint8_t bit = (char_data >> (15 - px)) & 1;
            uint16_t color = bit ? fg : bg;
            
            if (x + px < ST7735_WIDTH && y + py < ST7735_HEIGHT) {
                ST7735_DrawPixel(x + px, y + py, color);
            }
        }
    }
}

void ST7735_FillScreen(uint16_t color) {
    ST7735_BeginFrame();
    
    for (uint16_t i = 0; i < LINE_BUF_SIZE; i++) {
        line_buffer[i] = color;
    }
    
    for (uint16_t y = 0; y < ST7735_HEIGHT; y++) {
        ST7735_PushLine(line_buffer);
    }
    
    ST7735_EndFrame();
}

void ST7735_DrawImage(uint16_t x, uint16_t y, uint16_t w, uint16_t h, const uint16_t *data) {
    ST7735_Select();
    
    ST7735_WriteCmd(ST7735_CASET);
    uint8_t caset[] = {0x00, x, 0x00, (x + w - 1)};
    ST7735_WriteData(caset, 4);
    
    ST7735_WriteCmd(ST7735_RASET);
    uint8_t raset[] = {0x00, y, 0x00, (y + h - 1)};
    ST7735_WriteData(raset, 4);
    
    ST7735_WriteCmd(ST7735_RAMWR);
    ST7735_DATA();
    HAL_SPI_Transmit(&hspi1, (uint8_t *)data, w * h * 2, HAL_MAX_DELAY);
    
    ST7735_Unselect();
}

void ST7735_DrawString(uint16_t x, uint16_t y, const char *str, FontDef font, uint16_t fg, uint16_t bg) {
    uint16_t xpos = x;
    uint16_t ypos = y;
    
    while (*str) {
        if (*str == '\n') {
            xpos = x;
            ypos += font.height;
            str++;
            continue;
        }
        
        if (*str == '\r') {
            xpos = x;
            str++;
            continue;
        }
        
        if (ypos + font.height > ST7735_HEIGHT) {
            break;
        }
        
        if (xpos + font.width > ST7735_WIDTH) {
            xpos = x;
            ypos += font.height;
            
            if (ypos + font.height > ST7735_HEIGHT) {
                break;
            }
        }
        
        ST7735_RenderChar(xpos, ypos, *str, font, fg, bg);
        
        xpos += font.width;
        str++;
    }
}

uint16_t ST7735_GetWidth(void) {
    return ST7735_WIDTH;
}

uint16_t ST7735_GetHeight(void) {
    return ST7735_HEIGHT;
}

void ST7735_SetOrientation(uint8_t orientation) {
    ST7735_Select();
    ST7735_WriteCmd(ST7735_MADCTL);
    uint8_t madctl;
    
    switch(orientation) {
        case 0:  // Portrait
            madctl = ST7735_MADCTL_MX | ST7735_MADCTL_MY | ST7735_MADCTL_RGB;
            break;
        case 1:  // Landscape (90° CW)
            madctl = ST7735_MADCTL_MV | ST7735_MADCTL_MX | ST7735_MADCTL_RGB;
            break;
        case 2:  // Portrait (180°)
            madctl = ST7735_MADCTL_RGB;
            break;
        case 3:  // Landscape (270°)
            madctl = ST7735_MADCTL_MV | ST7735_MADCTL_MY | ST7735_MADCTL_RGB;
            break;
        default:
            madctl = ST7735_MADCTL_MV | ST7735_MADCTL_MX | ST7735_MADCTL_RGB;
    }
    
    uint8_t data[] = {madctl};
    ST7735_WriteData(data, 1);
    ST7735_Unselect();
}

